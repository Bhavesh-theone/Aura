from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from aura.core.domain.enums import (CriterionHardness, CriterionOperator, MandateSide,
                                    MandateStatus)


@dataclass
class MandateCriterion:
    """SOSPE §6.2: one rule the client set. `value` is JSON (a list for in / not_in /
    between, a number for gte / lte)."""
    criterion_key: str
    operator: CriterionOperator
    value: Any
    hardness: CriterionHardness
    weight: float | None = None


@dataclass
class Mandate:
    id: int | None
    deal_id: int
    title: str
    notes: str
    side: MandateSide
    status: MandateStatus
    created_at: datetime
    criteria: list[MandateCriterion] = field(default_factory=list)
