import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone

GENESIS_HASH = "0" * 64


@dataclass
class AuditEntry:
    id: int | None
    job_id: int | None
    actor: str
    action: str
    payload: dict
    created_at: datetime
    deal_id: int | None = None
    prev_hash: str = ""
    row_hash: str = ""


def compute_row_hash(prev_hash: str, entry: AuditEntry) -> str:
    """sha256(prev_hash + canonical json of the entry). created_at is normalised to naive
    UTC because the database hands datetimes back without a timezone."""
    created = entry.created_at
    if created.tzinfo is not None:
        created = created.astimezone(timezone.utc).replace(tzinfo=None)
    body = {"job_id": entry.job_id, "deal_id": entry.deal_id, "actor": entry.actor,
            "action": entry.action, "payload": entry.payload,
            "created_at": created.isoformat()}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256((prev_hash + canonical).encode("utf-8")).hexdigest()
