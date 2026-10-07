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
    created_by: str | None = None
    # The job.submit span: segments and model runs continue this trace (migration 0012).
    trace_id: str | None = None
    span_id: str | None = None


@dataclass
class IdempotencyRecord:
    """An Idempotency-Key seen on POST /api/jobs: the same key and body give the same job."""
    id: int | None
    key: str
    username: str
    request_hash: str
    job_id: int
    created_at: datetime
