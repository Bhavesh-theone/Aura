"""Deal exports: one deal as PDF / Word / Excel / JSON / ZIP of CSVs, and the deals list as
CSV / Excel. Read-only on the deal, but every export is audited ('deal_exported', with the
sha256 and size of the exact bytes sent) and traced, and rate-limited per user."""
import hashlib
import time
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from aura.api.deps import (current_user, get_agent_runs, get_anchor_path, get_audit,
                           get_conditions, get_contacts, get_deals, get_diligence,
                           get_documents, get_extractions, get_findings, get_handoffs,
                           get_history, get_mandates, get_parties, get_session, get_signoffs,
                           get_walls)
from aura.api.rate_limit import check_export
from aura.config import get_settings
from aura.core.clock import utcnow
from aura.core.domain.audit import AuditEntry
from aura.core.domain.user import User
from aura.core.policy.rbac_policy import Capability, require
from aura.core.services.deal_export import (ExportSources, build_deal_export, deals_list_table,
                                            filter_deals, iso)
from aura.core.services.deal_profile import get_schema
from aura.core.tracing import tracer
from aura.data.repositories.sql_export import SqlExportReader
from aura.data.verify_audit import chain_head, verify
from aura.exports import deal_filename, list_filename, render_deal, render_list

router = APIRouter(prefix="/api/deals", tags=["exports"])


def get_export_reader(s: Session = Depends(get_session),
                      user: User = Depends(current_user)) -> SqlExportReader:
    return SqlExportReader(s, user.username)


def _schema(transaction_class: str, version: int) -> dict | None:
    try:
        return get_schema(transaction_class, version)
    except Exception:  # an unknown class or version just renders raw keys
        return None


def _audit_status(session: Session, anchor_path: Path | None):
    def status() -> dict:
        result = verify(session, anchor_path)
        head = chain_head(session)
        return {"ok": result.ok, "broken_at": result.broken_at,
                "head_id": head[0] if head else None, "head_hash": head[1] if head else None,
                "anchor_head_id": result.anchor.head_id, "message": result.message,
                "verified_at": iso(utcnow())}
    return status


def _guard(content: bytes, started: float) -> None:
    settings = get_settings()
    if len(content) > settings.export_max_mb * 1024 * 1024:
        raise HTTPException(413, f"The export is larger than {settings.export_max_mb} MB; "
                                 "choose fewer sections")
    if time.monotonic() - started > settings.export_max_seconds:
        raise HTTPException(503, "The export took too long; choose fewer sections")


def _file_response(content: bytes, media_type: str, filename: str, sha: str) -> Response:
    return Response(content=content, media_type=media_type, headers={
        "Content-Disposition": f'attachment; filename="{filename}"; '
                               f"filename*=UTF-8''{filename}",
        "Cache-Control": "no-store", "X-Content-SHA256": sha,
        "X-Content-Type-Options": "nosniff"})


@router.get("/export")
def export_deals(format: Literal["csv", "xlsx"] = "csv", q: str | None = None,
                 transaction_class: list[str] | None = Query(None),
                 stage: list[str] | None = Query(None),
                 outcome: list[str] | None = Query(None),
                 user: User = Depends(current_user), deals=Depends(get_deals),
                 audit=Depends(get_audit)):
    """The deals list the viewer can see, with the list page's filters (repeat a parameter
    for several values; outcome OPEN means no outcome yet)."""
    require(user.role, Capability.EXPORT_DEAL, "export deals")
    check_export(user.username)
    started = time.monotonic()
    with tracer.span("deals.export", {"aura.export.format": format,
                                      "enduser.id": user.username}) as span:
        chosen = filter_deals(deals.list_all(), q, transaction_class, stage, outcome)
        table = deals_list_table(chosen, user.role)
        now = iso(utcnow())
        rendered = render_list(table, format, now, user.username)
        _guard(rendered.content, started)
        sha = hashlib.sha256(rendered.content).hexdigest()
        filename = list_filename(now, rendered.extension)
        span.set_attributes({"aura.export.bytes": len(rendered.content),
                             "aura.export.rows": len(table.rows), "aura.export.sha256": sha})
        audit.append(AuditEntry(
            id=None, job_id=None, deal_id=None, actor=user.username, action="deal_exported",
            created_at=utcnow(),
            payload={"scope": "deals_list", "format": format, "rows": len(table.rows),
                     "deal_ids": [d.id for d in chosen][:500],
                     "filters": {"q": q, "transaction_class": transaction_class,
                                 "stage": stage, "outcome": outcome},
                     "sha256": sha, "bytes": len(rendered.content), "filename": filename}))
    return _file_response(rendered.content, rendered.media_type, filename, sha)


@router.get("/{deal_id}/export")
def export_deal(deal_id: int, format: Literal["pdf", "docx", "xlsx", "json", "zip"] = "pdf",
                sections: str | None = None, user: User = Depends(current_user),
                s: Session = Depends(get_session),
                anchor_path: Path | None = Depends(get_anchor_path),
                deals=Depends(get_deals), history=Depends(get_history),
                walls=Depends(get_walls), parties=Depends(get_parties),
                contacts=Depends(get_contacts), mandates=Depends(get_mandates),
                documents=Depends(get_documents), diligence=Depends(get_diligence),
                findings=Depends(get_findings), conditions=Depends(get_conditions),
                signoffs=Depends(get_signoffs), extractions=Depends(get_extractions),
                handoffs=Depends(get_handoffs), agent_runs=Depends(get_agent_runs),
                reader=Depends(get_export_reader), audit=Depends(get_audit)):
    """One deal as a file. `sections` is a comma-separated subset (default: all). 404 if
    the deal is not on your wall; 403 for admin; 429 over exports_per_minute."""
    require(user.role, Capability.EXPORT_DEAL, "export deals")
    check_export(user.username)
    started = time.monotonic()
    with tracer.span("deal.export", {"aura.export.format": format, "enduser.id": user.username,
                                     "aura.export.sections": sections or "all"},
                     deal_id=deal_id) as span:
        src = ExportSources(
            deals=deals, history=history, walls=walls, parties=parties, contacts=contacts,
            mandates=mandates, documents=documents, diligence=diligence, findings=findings,
            conditions=conditions, signoffs=signoffs, extractions=extractions,
            handoffs=handoffs, agent_runs=agent_runs, reader=reader,
            audit_status=_audit_status(s, anchor_path), profile_schema=_schema)
        bundle = build_deal_export(deal_id, user.username, user.role, sections, src)
        rendered = render_deal(bundle, format)
        _guard(rendered.content, started)
        sha = hashlib.sha256(rendered.content).hexdigest()
        filename = deal_filename(bundle.deal["external_id"], bundle.deal["name"],
                                 bundle.generated_at, rendered.extension)
        span.set_attributes({"aura.export.bytes": len(rendered.content),
                             "aura.export.sha256": sha, "aura.export.upsi": bundle.upsi})
        audit.append(AuditEntry(
            id=None, job_id=None, deal_id=deal_id, actor=user.username, action="deal_exported",
            created_at=utcnow(),
            payload={"scope": "deal", "format": format, "sections": bundle.section_keys,
                     "sha256": sha, "bytes": len(rendered.content), "filename": filename,
                     "upsi": bundle.upsi, "audit_head_id": bundle.audit.get("head_id")}))
    return _file_response(rendered.content, rendered.media_type, filename, sha)
