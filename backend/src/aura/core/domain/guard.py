from dataclasses import dataclass, field
from datetime import datetime

from aura.core.domain.enums import DealStage, GuardSeverity, TransactionClass


@dataclass
class StageGuard:
    id: int | None
    from_stage: DealStage
    to_stage: DealStage
    transaction_class: TransactionClass | None
    guard_name: str
    sql_text: str
    severity: GuardSeverity
    override_role: str | None
    active: bool = True
    description: str = ""


@dataclass
class GuardEvaluation:
    id: int | None
    deal_id: int
    guard_id: int
    guard_name: str
    severity: GuardSeverity
    attempted_at: datetime
    result: bool
    detail: dict = field(default_factory=dict)
    actor: str = ""
    overridden_by: str | None = None
    override_justification: str | None = None
    description: str = ""
    override_role: str | None = None
    history_id: int | None = None
