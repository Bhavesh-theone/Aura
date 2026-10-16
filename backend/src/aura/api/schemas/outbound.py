from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class CreateContactRequest(BaseModel):
    name: str = Field(default="", max_length=200)
    email: str = Field(min_length=3, max_length=254)
    is_primary: bool = False


class ContactOut(BaseModel):
    id: int
    party_id: int
    name: str
    email: str
    is_primary: bool
    verified_at: datetime | None
    verified_by: str | None
    created_by: str
    created_at: datetime


class CreateSuppressionRequest(BaseModel):
    kind: Literal["email", "domain"]
    value: str = Field(min_length=3, max_length=254)
    reason: str = Field(default="", max_length=500)


class SuppressionOut(BaseModel):
    id: int
    kind: str
    value: str
    reason: str
    created_by: str
    created_at: datetime


class OutboundOut(BaseModel):
    id: int
    handoff_id: int
    job_id: int | None
    deal_id: int | None
    party_id: int | None
    to_email: str
    subject: str
    mode: str
    status: str
    gmail_id: str | None
    gmail_thread_id: str | None
    error: str | None
    created_at: datetime
    completed_at: datetime | None
    trace_id: str | None


class GmailIntegrationOut(BaseModel):
    """Connection status only: never a token or the client secret."""
    mode: str
    connected: bool
    account_email: str | None
    scopes: list[str]
    expires_at: datetime | None
    needs_reconnect: bool
    storage: str | None
    daily_limit: int
    sent_today: int
    connect_command: str
    detail: str | None


class OutboundMetricsOut(BaseModel):
    mode: str
    drafted: int
    sent: int
    blocked: int
    failed: int
    blocked_by_reason: dict[str, int]
    # Executions with no approved draft_email handoff behind them: must be 0.
    outbound_without_approval: int
