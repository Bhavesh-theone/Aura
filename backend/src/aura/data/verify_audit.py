"""Recompute the audit hash chain and compare it with the local anchor file.

`python -m aura.data.verify_audit` exits 1 on a break. The anchor (backend/data/
audit_anchor.json: head_id, head_hash, written_at) is what catches tail deletion: removing
the newest rows leaves a chain that still verifies by itself, but its head is then behind
(or different from) the anchored head. The anchor is advanced only after a clean check,
at app start-up, by the worker loop and by this command. WORM storage is deferred.
"""
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from aura.config import BACKEND_DIR, Settings, get_settings
from aura.core.domain.audit import GENESIS_HASH, compute_row_hash
from aura.data import mappers
from aura.data.models.tables import AuditRow


@dataclass
class AnchorStatus:
    head_id: int | None
    head_hash: str | None
    written_at: str | None
    ok: bool


@dataclass
class AuditVerification:
    ok: bool
    broken_at: int | None
    anchor: AnchorStatus
    message: str = "OK"


def default_anchor_path() -> Path | None:
    """backend/data/audit_anchor.json for the default database; beside the file for any
    other SQLite database (so a scratch copy never compares against the real anchor);
    AURA_AUDIT_ANCHOR_PATH overrides both. None for an in-memory database."""
    s = get_settings()
    if s.audit_anchor_path:
        return Path(s.audit_anchor_path)
    if s.database_url == Settings.model_fields["database_url"].default:
        return BACKEND_DIR / "data" / "audit_anchor.json"
    prefix = "sqlite:///"
    if s.database_url.startswith(prefix) and ":memory:" not in s.database_url:
        return Path(s.database_url[len(prefix):] + ".audit_anchor.json")
    return None


def verify_chain(session: Session) -> int | None:
    """Return the id of the first row whose link is broken, or None if the chain is intact."""
    prev = GENESIS_HASH
    for row in session.scalars(select(AuditRow).order_by(AuditRow.id)):
        entry = mappers.audit_to_domain(row)
        if row.prev_hash != prev or row.row_hash != compute_row_hash(prev, entry):
            return row.id
        prev = row.row_hash
    return None


def read_anchor(path: Path) -> dict | None:
    """The anchor file's content; None when there is no file. A file that cannot be read
    as an anchor raises ValueError: that is itself a failure, not an absence."""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data.get("head_id"), int) or not isinstance(data.get("head_hash"),
                                                                     str):
            raise ValueError("missing head_id or head_hash")
        return data
    except (OSError, ValueError, AttributeError) as exc:
        raise ValueError(f"audit anchor {path} is unreadable: {exc}") from exc


def write_anchor(path: Path, head_id: int, head_hash: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {"head_id": head_id, "head_hash": head_hash,
            "written_at": datetime.now(timezone.utc).isoformat()}
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(body, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _head(session: Session) -> tuple[int, str] | None:
    row = session.execute(select(AuditRow.id, AuditRow.row_hash)
                          .order_by(AuditRow.id.desc()).limit(1)).first()
    return (row[0], row[1]) if row else None


def verify(session: Session, anchor_file: Path | None) -> AuditVerification:
    """Chain check plus anchor comparison. broken_at is the first bad row; for a deleted
    tail it is the first id that should exist and does not."""
    chain_break = verify_chain(session)
    head = _head(session)
    try:
        anchor = read_anchor(anchor_file) if anchor_file else None
    except ValueError as exc:
        status = AnchorStatus(None, None, None, ok=False)
        return AuditVerification(False, chain_break, status, str(exc))
    if anchor is None:
        status = AnchorStatus(None, None, None, ok=True)
        anchor_broken_at, anchor_problem = None, ""
    else:
        anchored_id, anchored_hash = anchor["head_id"], anchor["head_hash"]
        if head is None or head[0] < anchored_id:
            ok, anchor_broken_at = False, (head[0] if head else 0) + 1
            anchor_problem = (f"audit tail deleted: chain head is id {head[0] if head else 0}"
                              f", anchor says id {anchored_id}")
        else:
            row_hash = session.scalar(select(AuditRow.row_hash)
                                      .where(AuditRow.id == anchored_id))
            ok = row_hash == anchored_hash
            anchor_broken_at = None if ok else anchored_id
            anchor_problem = "" if ok else f"audit entry {anchored_id} no longer matches the anchor"
        status = AnchorStatus(anchored_id, anchored_hash, anchor.get("written_at"), ok)

    ok = chain_break is None and status.ok
    broken_at = chain_break if chain_break is not None else anchor_broken_at
    if chain_break is not None:
        message = f"BROKEN at audit entry id {chain_break}"
    else:
        message = anchor_problem or "OK"
    return AuditVerification(ok, broken_at, status, message)


def refresh_anchor(session: Session, anchor_file: Path | None) -> AuditVerification:
    """Verify, and when everything is clean move the anchor up to the current head."""
    result = verify(session, anchor_file)
    head = _head(session)
    if result.ok and anchor_file is not None and head is not None:
        write_anchor(anchor_file, head[0], head[1])
        result = verify(session, anchor_file)
    return result


def main() -> int:
    from aura.data.engine import SessionLocal
    with SessionLocal() as session:
        result = refresh_anchor(session, default_anchor_path())
    print(result.message)
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
