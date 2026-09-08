from dataclasses import dataclass
from datetime import datetime


@dataclass
class AuditEntry:
    id: int | None
    job_id: int | None
    actor: str
    action: str
    payload: dict
    created_at: datetime
