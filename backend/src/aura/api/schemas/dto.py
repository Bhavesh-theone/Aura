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


class ApprovalResponse(BaseModel):
    id: int
    segment_id: int
    category: str
    proposed_action: dict
    status: str


class AuditResponse(BaseModel):
    id: int
    job_id: int | None
    actor: str
    action: str
    payload: dict
    created_at: datetime
