"""Deal intake: create a deal by uploading its documents (phase 3).

Every route acts as the caller: row-level security keeps a draft intake, its staged files
and their chunks visible to its creator only (anyone else gets 404). Every change is
audited; live progress goes to the creator over the WebSocket (entity_changed, kind
'intake'). Extraction runs in the worker, never in a request.
"""
from fastapi import APIRouter, Depends, File, Response, UploadFile, status
from pydantic import BaseModel, ConfigDict

from aura.api.deps import (current_user, get_audit, get_deals, get_history, get_mandates,
                           get_parties, get_session, get_store, get_users, get_walls)
from aura.config import get_settings
from aura.core.domain.errors import NotFound
from aura.core.domain.user import User
from aura.core.services import intake as svc
from aura.core.services import intake_fields as F
from aura.data.repositories.sql_ingest import SqlIndexQueue
from aura.data.repositories.sql_intake import SqlIntakeRepository
from aura.ingest.parsers import check_upload, limits_from_settings

router = APIRouter(prefix="/api/intakes", tags=["intakes"])


class CreateIntakeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    company_name: str | None = None
    cin: str | None = None
    transaction_class_hint: str | None = None


class PatchIntakeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    transaction_class: str | None = None
    external_id: str | None = None
    hints: dict | None = None
    fields: dict[str, dict] | None = None
    conflicts: dict[str, dict] | None = None
    files: dict[str, dict] | None = None


class ConfirmIntakeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    external_id: str | None = None
    name: str | None = None


def get_intakes(s=Depends(get_session), user: User = Depends(current_user)):
    return SqlIntakeRepository(s, user.username)


# ------------------------------------------------------------------------ presentation

def file_out(doc, stage: str) -> dict:
    return {"id": doc.id, "filename": doc.filename, "doc_class": doc.doc_class.value,
            "byte_size": doc.byte_size, "sha256": doc.sha256, "version": doc.current_version,
            "sensitivity": doc.sensitivity, "contains_upsi": doc.contains_upsi,
            "stage": stage, "page_count": doc.page_count, "chunk_count": doc.chunk_count,
            "ocr_used": doc.ocr_used, "warnings": list(doc.index_warnings or []),
            "error": doc.index_error, "uploaded_at": doc.uploaded_at.isoformat()}


def _title(intake) -> str:
    name = (intake.fields.get("company_name") or {}).get("value") or \
        (intake.hints or {}).get("company_name")
    return str(name) if name else "Untitled intake"


def intake_out(intake, intakes: SqlIntakeRepository) -> dict:
    threshold = get_settings().intake_confidence_threshold
    files = intakes.files(intake.id) if intake.status != "confirmed" else []
    jobs = intakes.file_stages(intake.id) if files else {}
    stages = {d.id: svc.file_stage(d, jobs.get(d.id)) for d in files}
    review = svc.review(intake, stages, threshold)
    specs = svc.specs_for(intake)
    fields: dict[str, dict] = {}
    for spec in specs:
        rec = intake.fields.get(spec.key) or {}
        needs, confirm = review.field_flags.get(spec.key, (False, False))
        fields[spec.key] = {
            **spec.as_dict(), "value": rec.get("value"), "auto_value": rec.get("auto_value"),
            "confidence": rec.get("confidence"), "source": rec.get("source"),
            "citations": rec.get("citations") or [], "needs_review": needs,
            "requires_confirmation": confirm, "accepted": bool(rec.get("accepted")),
            "edited": bool(rec.get("edited")),
            "error": review.errors.get(spec.key) or rec.get("error"),
            "conflict_id": rec.get("conflict_id") if any(
                c["id"] == rec.get("conflict_id") and not c.get("resolved")
                for c in intake.conflicts) else None,
            "note": rec.get("note")}
    groups = [{"id": g, "label": label, "fields": [s.key for s in specs if s.group == g]}
              for g, label in F.GROUPS]
    groups = [g for g in groups if g["fields"]]
    meta = intake.extract_meta or {}
    return {
        "id": intake.id, "status": intake.status, "title": _title(intake),
        "created_by": intake.created_by,
        "created_at": intake.created_at.isoformat() if intake.created_at else None,
        "updated_at": intake.updated_at.isoformat() if intake.updated_at else None,
        "hints": {k: (intake.hints or {}).get(k)
                  for k in ("company_name", "cin", "transaction_class_hint")},
        "transaction_class": intake.transaction_class, "external_id": intake.external_id,
        "progress": svc.progress_view(intake, files, stages),
        "extraction": {
            "status": "failed" if intake.extract_status == "dead_letter"
            else intake.extract_status,
            "attempts": intake.extract_attempts, "error": intake.extract_error,
            "started_at": meta.get("started_at"), "finished_at": meta.get("finished_at"),
            "duration_ms": meta.get("duration_ms"), "model": meta.get("model"),
            "llm_used": bool(meta.get("llm_used")), "warnings": meta.get("warnings") or []},
        "files": [file_out(d, stages[d.id]) for d in files],
        "groups": groups, "fields": fields, "conflicts": intake.conflicts or [],
        "review": {"needs_review": review.needs_review,
                   "unresolved_conflicts": review.unresolved_conflicts,
                   "missing_required": review.missing_required, "errors": review.errors,
                   "ready": review.ready},
        "confirmed_deal_id": intake.confirmed_deal_id}


def summary_out(intake, intakes: SqlIntakeRepository) -> dict:
    files = intakes.files(intake.id)
    jobs = intakes.file_stages(intake.id) if files else {}
    stages = {d.id: svc.file_stage(d, jobs.get(d.id)) for d in files}
    return {"id": intake.id, "status": intake.status, "title": _title(intake),
            "transaction_class": intake.transaction_class, "files": len(files),
            "progress": svc.progress_view(intake, files, stages),
            "created_at": intake.created_at.isoformat() if intake.created_at else None,
            "updated_at": intake.updated_at.isoformat() if intake.updated_at else None}


# ------------------------------------------------------------------------ routes

@router.post("", status_code=status.HTTP_201_CREATED)
def create(body: CreateIntakeRequest | None = None, user: User = Depends(current_user),
           intakes=Depends(get_intakes), audit=Depends(get_audit)):
    intake = svc.create_intake(body.model_dump() if body else {}, user.username, user.role,
                               intakes, audit)
    return intake_out(intake, intakes)


@router.get("")
def list_open(user: User = Depends(current_user), intakes=Depends(get_intakes)):
    """My open drafts (draft, processing, review), most recently changed first."""
    return [summary_out(i, intakes) for i in intakes.list_open()]


@router.get("/{intake_id}")
def get(intake_id: int, user: User = Depends(current_user), intakes=Depends(get_intakes)):
    intake = intakes.get(intake_id)
    if intake is None:
        raise NotFound("Intake not found")
    return intake_out(intake, intakes)


@router.post("/{intake_id}/files", status_code=status.HTTP_201_CREATED)
def upload(intake_id: int, files: list[UploadFile] = File(...),
           user: User = Depends(current_user), intakes=Depends(get_intakes),
           store=Depends(get_store), audit=Depends(get_audit), session=Depends(get_session)):
    """Stage one or more files (415 unsupported type, 413 too large: the same limits as
    deal documents). Re-uploading the same bytes is idempotent ('duplicate': true)."""
    limit = limits_from_settings().max_bytes
    uploads = []
    for f in files:
        name = f.filename or "unnamed"
        content = f.file.read(limit + 1)
        check_upload(name, content)
        uploads.append((name, content))
    staged = svc.stage_files(intake_id, uploads, user.username, user.role, intakes, store,
                             audit, SqlIndexQueue(session, user.username), intakes,
                             get_settings().intake_max_files)
    intake = intakes.get(intake_id)
    jobs = intakes.file_stages(intake_id)
    docs = {d.id: d for d in intakes.files(intake_id)}
    return {"files": [{**file_out(docs.get(s.document.id, s.document),
                                  svc.file_stage(docs.get(s.document.id, s.document),
                                                 jobs.get(s.document.id))),
                       "duplicate": s.duplicate} for s in staged],
            "intake": intake_out(intake, intakes)}


@router.delete("/{intake_id}/files/{file_id}")
def remove_file(intake_id: int, file_id: int, user: User = Depends(current_user),
                intakes=Depends(get_intakes), audit=Depends(get_audit)):
    return intake_out(svc.remove_file(intake_id, file_id, user.username, user.role, intakes,
                                      audit), intakes)


@router.post("/{intake_id}/extract", status_code=status.HTTP_202_ACCEPTED)
def extract(intake_id: int, user: User = Depends(current_user),
            intakes=Depends(get_intakes), audit=Depends(get_audit)):
    """Queue extraction again (it also starts by itself once every file is indexed)."""
    return intake_out(svc.request_extraction(intake_id, user.username, user.role, intakes,
                                             audit), intakes)


@router.patch("/{intake_id}")
def patch(intake_id: int, body: PatchIntakeRequest, user: User = Depends(current_user),
          intakes=Depends(get_intakes), audit=Depends(get_audit)):
    """Autosaved edits: field values, accepts, conflict picks, class, deal id, file class."""
    return intake_out(svc.update_intake(intake_id, body.model_dump(exclude_unset=True),
                                        user.username, user.role, intakes, audit), intakes)


@router.get("/{intake_id}/chunks/{chunk_id}")
def chunk(intake_id: int, chunk_id: int, user: User = Depends(current_user),
          intakes=Depends(get_intakes)):
    """A cited passage with the text of its page(s), for the review's citation pane."""
    if intakes.get(intake_id) is None:
        raise NotFound("Intake not found")
    c = intakes.chunk(intake_id, chunk_id)
    if c is None:
        raise NotFound("Passage not found")
    return {"chunk_id": c.chunk_id, "document_id": c.document_id, "filename": c.filename,
            "page_from": c.page_from, "page_to": c.page_to, "kind": c.kind,
            "heading": c.meta.get("heading"), "text": c.text,
            "page_text": intakes.page_text(c.document_id, c.page_from, c.page_to)}


@router.post("/{intake_id}/confirm", status_code=status.HTTP_201_CREATED)
def confirm(intake_id: int, body: ConfirmIntakeRequest | None = None,
            user: User = Depends(current_user), intakes=Depends(get_intakes),
            deals=Depends(get_deals), history=Depends(get_history), audit=Depends(get_audit),
            walls=Depends(get_walls), users=Depends(get_users), parties=Depends(get_parties),
            mandates=Depends(get_mandates)):
    """Create the deal: 409 when already confirmed, 422 with field_errors when not ready."""
    body = body or ConfirmIntakeRequest()
    # IntakeInvalid -> 422 {detail, field_errors} (aura.api.errors); raising rolls the whole
    # unit of work back, so a half-made deal is never committed.
    result = svc.confirm_intake(intake_id, body.external_id, body.name, user.username,
                                user.role, get_settings().intake_confidence_threshold,
                                intakes, deals, history, audit, walls, users, parties,
                                mandates)
    return {"deal_id": result.deal.id, "external_id": result.deal.external_id,
            "name": result.deal.name, "warnings": result.warnings,
            "intake": intake_out(result.intake, intakes)}


@router.delete("/{intake_id}", status_code=status.HTTP_204_NO_CONTENT)
def discard(intake_id: int, user: User = Depends(current_user), intakes=Depends(get_intakes),
            audit=Depends(get_audit)):
    svc.discard_intake(intake_id, user.username, user.role, intakes, audit)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
