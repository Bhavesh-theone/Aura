from datetime import datetime

from pydantic import BaseModel

from aura.api.schemas.dto import AuditResponse
from aura.core.domain.enums import AssignmentMode, HandoffDirection, HandoffTrigger


class HandoffOut(BaseModel):
    id: int
    deal_id: int | None
    task_id: int
    job_id: int | None
    task_type: str
    direction: str
    trigger: str
    context_package: dict
    directive: dict | None
    status: str
    created_at: datetime
    auto_escalate_at: datetime | None
    resolved_by: str | None
    resolved_at: datetime | None


class CreateHandoffRequest(BaseModel):
    """context_package and directive are validated by the service so every breach comes
    back as a 422 with the same body shape."""
    deal_id: int | None = None
    job_id: int | None = None
    task_type: str
    assignment_mode: AssignmentMode = AssignmentMode.BOT_SUPERVISED
    direction: HandoffDirection = HandoffDirection.BOT_TO_HUMAN
    trigger: HandoffTrigger = HandoffTrigger.EXPLICIT_REQUEST
    context_package: dict
    directive: dict | None = None
    materiality_inr: int | None = None


class AgentRunOut(BaseModel):
    id: int
    job_id: int | None
    deal_id: int | None
    task_id: int | None
    archetype: str
    model_id: str
    model_version: str
    prompt_template_id: str
    prompt_hash: str
    confidence: float | None
    tokens_in: int
    tokens_out: int
    cost_inr: float
    latency_ms: int
    started_at: datetime
    completed_at: datetime
    tool_calls: list
    # The llm.call span the run was recorded under (GET /api/traces/{trace_id}).
    trace_id: str | None = None
    span_id: str | None = None


class AgentRunDetailOut(AgentRunOut):
    input_digest: dict
    output: dict


class DashboardOut(BaseModel):
    open_deals: int
    deals_by_class: dict[str, int]
    deals_by_stage: dict[str, int]
    decisions_waiting: int
    blockers_open: int
    closed_deals: int
    ended_deals: int
    recent_activity: list[AuditResponse]
