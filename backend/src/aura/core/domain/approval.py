from dataclasses import dataclass
from datetime import datetime

from aura.core.domain.enums import ActionCategory, ApprovalStatus


@dataclass
class Approval:
    id: int | None
    segment_id: int
    category: ActionCategory
    proposed_action: dict
    status: ApprovalStatus
    decided_by: int | None = None
    decided_at: datetime | None = None
