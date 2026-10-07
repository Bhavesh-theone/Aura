from datetime import datetime

from pydantic import BaseModel


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class MeResponse(BaseModel):
    id: int
    username: str
    role: str


class SubmitJobRequest(BaseModel):
    inputs: dict
    deal_id: int | None = None


class JobResponse(BaseModel):
    id: int
    status: str
    inputs: dict
    result: dict | None
    deal_id: int | None
    created_at: datetime
    created_by: str | None = None


class DeadLetterResponse(BaseModel):
    """A job whose segment ran out of retries. POST /api/jobs/{job_id}/retry queues it again."""
    job: JobResponse
    segment_id: int
    seq: int
    status: str
    attempts: int
    last_error: str | None
    claimed_by: str | None
    ended_at: datetime | None


class AuditResponse(BaseModel):

    id: int
    job_id: int | None
    deal_id: int | None = None
    actor: str
    action: str
    payload: dict
    created_at: datetime
    prev_hash: str = ""
    row_hash: str = ""
