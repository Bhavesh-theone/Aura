from dataclasses import dataclass
from datetime import datetime

from aura.core.domain.enums import JobStatus


@dataclass
class Job:
    id: int | None
    status: JobStatus
    inputs: dict
    deal_id: int | None
    result: dict | None
    created_at: datetime
