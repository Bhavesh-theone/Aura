from dataclasses import dataclass, field
from datetime import datetime

from aura.core.domain.enums import ActionCategory, SegmentStatus


@dataclass
class ProposedAction:
    tool: str
    category: ActionCategory
    arguments: dict
    summary: str


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
