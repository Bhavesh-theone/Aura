from dataclasses import dataclass, field

from datetime import datetime

from aura.core.domain.enums import (ChecklistLayer, CPStatus, DiligenceSeverity,
                                    DiligenceStatus, FindingType, TransactionClass)


@dataclass
class ChecklistTemplate:
    id: int | None
    transaction_class: TransactionClass | None
    layer: ChecklistLayer
    version: int
    name: str


@dataclass
class ChecklistItemTemplate:
    id: int | None
    transaction_class: TransactionClass | None
    category: str
    prompt: str
    default_severity: DiligenceSeverity
    template_id: int | None = None


@dataclass
class DiligenceItem:
    id: int | None
    deal_id: int
    template_id: int | None
    prompt: str
    severity: DiligenceSeverity
    status: DiligenceStatus = DiligenceStatus.OPEN
    evidence_doc_ids: list[int] = field(default_factory=list)
    waiver_justification: str | None = None


@dataclass
class ConditionPrecedent:
    id: int | None
    deal_id: int
    description: str
    cp_type: str
    status: CPStatus = CPStatus.OPEN
    waiver_justification: str | None = None


@dataclass
class Finding:
    id: int | None
    diligence_item_id: int
    deal_id: int
    finding_type: FindingType
    description: str
    quantified_impact_inr: int | None
    affects_valuation: bool
    raised_by: str
    raised_at: datetime
