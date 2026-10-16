from dataclasses import dataclass, field
from datetime import datetime

from aura.core.domain.enums import DealStage, Outcome, TransactionClass


@dataclass
class Deal:
    id: int | None
    external_id: str
    name: str
    stage: DealStage
    transaction_class: TransactionClass
    owner: str
    outcome: Outcome | None
    opened_at: datetime
    closed_at: datetime | None = None
    regulatory_flags: list[str] = field(default_factory=list)
    # Class-specific terms, validated against the class's JSON Schema at this version.
    profile: dict = field(default_factory=dict)
    profile_schema_version: int = 1


@dataclass
class StageHistoryEntry:
    id: int | None
    deal_id: int
    from_stage: DealStage | None
    to_stage: DealStage
    entered_at: datetime
    actor: str
    reason_code: str | None
    is_regression: bool


@dataclass
class DealSignoff:
    id: int | None
    deal_id: int
    signed_by: str
    note: str
    signed_at: datetime
