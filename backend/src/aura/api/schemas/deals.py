from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from aura.core.domain.enums import (CPStatus, CriterionHardness, CriterionOperator, DealStage,
                                    DiligenceStatus, DocClass, FindingType, IdentifierScheme,
                                    MandateSide, MandateStatus, PartyRole, PartyType, Role,
                                    TransactionClass)


class DealOut(BaseModel):
    id: int
    external_id: str
    name: str
    stage: str
    transaction_class: str
    owner: str
    outcome: str | None
    opened_at: datetime
    closed_at: datetime | None
    regulatory_flags: list[str]


class DealPartyOut(BaseModel):
    party_id: int
    display_name: str
    role: str


class HistoryOut(BaseModel):
    from_stage: str | None
    to_stage: str
    entered_at: datetime
    actor: str
    reason_code: str | None
    is_regression: bool


class DealDetailOut(DealOut):
    parties: list[DealPartyOut]
    history: list[HistoryOut]
    allowed_next: list[str]


class CreateDealRequest(BaseModel):
    external_id: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=200)
    transaction_class: TransactionClass


class EvaluationOut(BaseModel):
    guard_name: str
    result: bool
    detail: dict
    severity: str
    description: str = ""
    overridden_by: str | None = None
    override_role: str | None = None


class TransitionRequest(BaseModel):
    to_stage: DealStage
    reason_code: str | None = None
    override_justification: str | None = None


class TransitionOut(BaseModel):
    deal: DealOut
    evaluations: list[EvaluationOut]


class IdentifierIO(BaseModel):
    scheme: IdentifierScheme
    value: str


class CreatePartyRequest(BaseModel):
    party_type: PartyType
    display_name: str = Field(min_length=1, max_length=200)
    identifiers: list[IdentifierIO] = []


class PartyOut(BaseModel):
    id: int
    party_type: str
    display_name: str
    identifiers: list[IdentifierIO]


class LinkPartyRequest(BaseModel):
    party_id: int
    role: PartyRole


class CriterionIO(BaseModel):
    """SOSPE §6.2 mandate criterion. `value` is JSON: a list for in / not_in / between,
    a number for gte / lte."""
    criterion_key: str = Field(min_length=1, max_length=100)
    operator: CriterionOperator
    value: Any
    hardness: CriterionHardness
    weight: float | None = Field(default=None, ge=0, le=1)


class CreateMandateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    notes: str = ""
    side: MandateSide
    status: MandateStatus = MandateStatus.ACTIVE
    criteria: list[CriterionIO] = []


class MandateOut(BaseModel):
    id: int
    deal_id: int
    title: str
    notes: str
    side: str
    status: str
    created_at: datetime
    criteria: list[CriterionIO]


class DocumentOut(BaseModel):
    id: int
    deal_id: int
    doc_class: str
    filename: str
    sha256: str
    byte_size: int
    current_version: int
    contains_upsi: bool
    sensitivity: int
    is_executed: bool
    class_confirmed: bool
    uploaded_by: str
    uploaded_at: datetime


class DiligenceItemOut(BaseModel):
    id: int
    deal_id: int
    template_id: int | None
    prompt: str
    severity: str
    status: str
    evidence_doc_ids: list[int]
    waiver_justification: str | None


class UpdateDiligenceRequest(BaseModel):
    status: DiligenceStatus
    evidence_doc_ids: list[int] | None = None
    waiver_justification: str | None = None


class CreateConditionRequest(BaseModel):
    description: str = Field(min_length=1)
    cp_type: str = Field(min_length=1, max_length=64)


class UpdateConditionRequest(BaseModel):
    status: CPStatus
    waiver_justification: str | None = None


class ConditionOut(BaseModel):
    id: int
    deal_id: int
    description: str
    cp_type: str
    status: str
    waiver_justification: str | None


class MemberRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)


class MemberOut(BaseModel):
    username: str
    added_at: datetime


class AnchorOut(BaseModel):
    head_id: int | None
    head_hash: str | None
    written_at: str | None
    ok: bool


class AuditVerifyOut(BaseModel):
    ok: bool
    broken_at: int | None
    anchor: AnchorOut


class UpdateDocumentRequest(BaseModel):
    is_executed: bool | None = None
    doc_class: DocClass | None = None


class DocumentVersionOut(BaseModel):
    version: int
    sha256: str
    byte_size: int
    uploaded_by: str
    uploaded_at: datetime


class UpdateDealRequest(BaseModel):
    regulatory_flags: list[str]


class SignoffRequest(BaseModel):
    note: str = ""


class SignoffOut(BaseModel):
    id: int
    deal_id: int
    signed_by: str
    note: str
    signed_at: datetime


class CreateFindingRequest(BaseModel):
    diligence_item_id: int
    finding_type: FindingType
    description: str = Field(min_length=1)
    quantified_impact_inr: int | None = None
    affects_valuation: bool = False


class FindingOut(BaseModel):
    id: int
    diligence_item_id: int
    deal_id: int
    finding_type: str
    description: str
    quantified_impact_inr: int | None
    affects_valuation: bool
    raised_by: str
    raised_at: datetime


class ExtractionOut(BaseModel):
    id: int
    document_id: int
    schema_name: str
    payload: dict
    confidence: float
    feeds_valuation: bool
    human_verified_by: str | None
    human_verified_at: datetime | None
    created_at: datetime


class UserOut(BaseModel):
    id: int
    username: str
    role: str
    active: bool


class CreateUserRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=200)
    role: Role


class UpdateUserRequest(BaseModel):
    role: Role | None = None
    active: bool | None = None


class StageDwellOut(BaseModel):
    stage: str
    n: int
    median_hours: float
    p90_hours: float


class SuccessMetricsOut(BaseModel):
    guarded_forward_transitions_pct: float
    runs_traceable_pct: float
    audit_chain_ok: bool
    handoff_rejections_422: int
    outbound_executed: int
    deals_closed_end_to_end: int


class ReliabilityMetricsOut(BaseModel):
    dead_lettered_segments: int
    retried_segments: int
    recovered_segments: int
    fallback_runs: int
    budget_deferrals: int


class MetricsOut(BaseModel):
    stage_dwell: list[StageDwellOut]
    success: SuccessMetricsOut
    reliability: ReliabilityMetricsOut | None = None

