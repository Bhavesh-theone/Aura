from dataclasses import dataclass
from datetime import datetime

from aura.core.domain.enums import (AssignmentMode, HandoffDirection, HandoffStatus,
                                    HandoffTrigger, TaskStatus)


@dataclass
class Task:
    id: int | None
    deal_id: int | None
    job_id: int | None
    task_type: str
    assignment_mode: AssignmentMode
    status: TaskStatus
    materiality_inr: int | None
    created_at: datetime


@dataclass
class Handoff:
    id: int | None
    task_id: int
    deal_id: int | None
    direction: HandoffDirection
    trigger: HandoffTrigger
    context_package: dict
    directive: dict | None
    status: HandoffStatus
    auto_escalate_at: datetime | None
    created_at: datetime
    resolved_by: str | None = None
    resolved_at: datetime | None = None
    # Convenience copies of task fields, filled by the repository on read.
    job_id: int | None = None
    task_type: str = ""
