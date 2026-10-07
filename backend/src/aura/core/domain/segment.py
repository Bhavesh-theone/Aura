from dataclasses import dataclass, field
from datetime import datetime

from aura.core.domain.enums import ActionCategory, SegmentStatus


@dataclass
class ProposedAction:
    tool: str
    category: ActionCategory
    arguments: dict
    summary: str
    materiality_inr: int | None = None
    # Other gated tool calls the agent attempted in the same run. None of them ran; they are
    # shown to the person as evidence rather than silently dropped.
    additional_gated_attempts: list[dict] = field(default_factory=list)



@dataclass
class Segment:
    id: int | None
    job_id: int
    seq: int
    status: SegmentStatus
    context_in: dict = field(default_factory=dict)
    context_out: dict | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    # Reliability state (migration 0011): who holds the claim and since when, how many
    # times it has been claimed, when it may next run, and why the last attempt failed.
    claimed_by: str | None = None
    claimed_at: datetime | None = None
    attempts: int = 0
    not_before: datetime | None = None
    last_error: str | None = None
