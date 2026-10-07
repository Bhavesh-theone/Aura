"""ORM <-> domain translation. ORM rows never escape the data package."""
from aura.core.domain.agent_run import AgentRun
from aura.core.domain.audit import AuditEntry
from aura.core.domain.deal import Deal, DealSignoff, StageHistoryEntry
from aura.core.domain.diligence import (ChecklistItemTemplate, ConditionPrecedent,
                                        DiligenceItem, Finding)
from aura.core.domain.document import Document, DocumentVersion
from aura.core.domain.extraction import Extraction
from aura.core.domain.enums import (AssignmentMode, CPStatus, DealStage, DiligenceSeverity,
                                    DiligenceStatus, DocClass, FindingType, GuardSeverity,
                                    HandoffDirection, HandoffStatus, HandoffTrigger,
                                    IdentifierScheme, JobStatus, Outcome, PartyType, Role,
                                    SegmentStatus, TaskStatus, TransactionClass)
from aura.core.domain.guard import StageGuard
from aura.core.domain.handoff import Handoff, Task
from aura.core.domain.job import Job
from aura.core.domain.party import Party, PartyIdentifier
from aura.core.domain.segment import Segment
from aura.core.domain.user import User
from aura.data.models.tables import (AgentRunRow, AuditRow, ChecklistItemTemplateRow,
                                     ConditionPrecedentRow, DealRow, DealSignoffRow,
                                     DealStageHistoryRow, DiligenceItemRow, DocumentRow,
                                     DocVersionRow, ExtractionRow, FindingRow, JobRow,
                                     HandoffRow, PartyIdentifierRow, PartyRow, SegmentRow,
                                     StageGuardRow, TaskRow, UserRow)


def job_to_domain(row: JobRow) -> Job:
    return Job(id=row.id, status=JobStatus(row.status), inputs=row.inputs or {},
               deal_id=row.deal_id, result=row.result, created_at=row.created_at,
               created_by=row.created_by, trace_id=row.trace_id, span_id=row.span_id)


def segment_to_domain(row: SegmentRow) -> Segment:
    return Segment(id=row.id, job_id=row.job_id, seq=row.seq,
                   status=SegmentStatus(row.status), context_in=row.context_in or {},
                   context_out=row.context_out, started_at=row.started_at,
                   ended_at=row.ended_at, claimed_by=row.claimed_by,
                   claimed_at=row.claimed_at, attempts=row.attempts or 0,
                   not_before=row.not_before, last_error=row.last_error)


def audit_to_domain(row: AuditRow) -> AuditEntry:
    return AuditEntry(id=row.id, job_id=row.job_id, actor=row.actor, action=row.action,
                      payload=row.payload or {}, created_at=row.created_at,
                      deal_id=row.deal_id, prev_hash=row.prev_hash, row_hash=row.row_hash)


def user_to_domain(row: UserRow) -> User:
    return User(id=row.id, username=row.username, password_hash=row.password_hash,
                role=Role(row.role), active=bool(row.active))


def deal_to_domain(row: DealRow) -> Deal:
    return Deal(id=row.id, external_id=row.external_id, name=row.name,
                stage=DealStage(row.stage),
                transaction_class=TransactionClass(row.transaction_class),
                owner=row.owner, outcome=Outcome(row.outcome) if row.outcome else None,
                opened_at=row.opened_at, closed_at=row.closed_at,
                regulatory_flags=list(row.regulatory_flags or []))


def history_to_domain(row: DealStageHistoryRow) -> StageHistoryEntry:
    return StageHistoryEntry(
        id=row.id, deal_id=row.deal_id,
        from_stage=DealStage(row.from_stage) if row.from_stage else None,
        to_stage=DealStage(row.to_stage), entered_at=row.entered_at, actor=row.actor,
        reason_code=row.reason_code, is_regression=row.is_regression)


def guard_to_domain(row: StageGuardRow) -> StageGuard:
    return StageGuard(
        id=row.id, from_stage=DealStage(row.from_stage), to_stage=DealStage(row.to_stage),
        transaction_class=(TransactionClass(row.transaction_class)
                           if row.transaction_class else None),
        guard_name=row.guard_name, sql_text=row.sql_text,
        severity=GuardSeverity(row.severity), override_role=row.override_role,
        active=row.active, description=row.description or "")


def party_to_domain(row: PartyRow, identifiers: list[PartyIdentifierRow]) -> Party:
    return Party(id=row.id, party_type=PartyType(row.party_type),
                 display_name=row.display_name, created_at=row.created_at,
                 identifiers=[PartyIdentifier(IdentifierScheme(i.scheme), i.value)
                              for i in identifiers])


def document_to_domain(row: DocumentRow) -> Document:
    return Document(id=row.id, deal_id=row.deal_id, doc_class=DocClass(row.doc_class),
                    filename=row.filename, sha256=row.sha256, byte_size=row.byte_size,
                    current_version=row.current_version, contains_upsi=row.contains_upsi,
                    sensitivity=row.sensitivity, uploaded_by=row.uploaded_by,
                    uploaded_at=row.uploaded_at, class_confirmed=row.class_confirmed,
                    is_executed=bool(row.is_executed))


def doc_version_to_domain(row: DocVersionRow) -> DocumentVersion:
    return DocumentVersion(document_id=row.document_id, version=row.version,
                           sha256=row.sha256, byte_size=row.byte_size,
                           uploaded_by=row.uploaded_by, uploaded_at=row.uploaded_at)


def template_to_domain(row: ChecklistItemTemplateRow) -> ChecklistItemTemplate:
    return ChecklistItemTemplate(
        id=row.id,
        transaction_class=(TransactionClass(row.transaction_class)
                           if row.transaction_class else None),
        category=row.category, prompt=row.prompt,
        default_severity=DiligenceSeverity(row.default_severity),
        template_id=row.template_id)


def diligence_to_domain(row: DiligenceItemRow) -> DiligenceItem:
    return DiligenceItem(id=row.id, deal_id=row.deal_id, template_id=row.template_id,
                         prompt=row.prompt, severity=DiligenceSeverity(row.severity),
                         status=DiligenceStatus(row.status),
                         evidence_doc_ids=list(row.evidence_doc_ids or []),
                         waiver_justification=row.waiver_justification)


def condition_to_domain(row: ConditionPrecedentRow) -> ConditionPrecedent:
    return ConditionPrecedent(id=row.id, deal_id=row.deal_id, description=row.description,
                              cp_type=row.cp_type, status=CPStatus(row.status),
                              waiver_justification=row.waiver_justification)


def task_to_domain(row: TaskRow) -> Task:
    return Task(id=row.id, deal_id=row.deal_id, job_id=row.job_id, task_type=row.task_type,
                assignment_mode=AssignmentMode(row.assignment_mode),
                status=TaskStatus(row.status), materiality_inr=row.materiality_inr,
                created_at=row.created_at)


def handoff_to_domain(row: HandoffRow, job_id: int | None, task_type: str) -> Handoff:
    return Handoff(
        id=row.id, task_id=row.task_id, deal_id=row.deal_id,
        direction=HandoffDirection(row.direction), trigger=HandoffTrigger(row.trigger),
        context_package=row.context_package or {}, directive=row.directive,
        status=HandoffStatus(row.status), auto_escalate_at=row.auto_escalate_at,
        created_at=row.created_at, resolved_by=row.resolved_by, resolved_at=row.resolved_at,
        job_id=job_id, task_type=task_type)


def agent_run_to_domain(row: AgentRunRow) -> AgentRun:
    return AgentRun(
        id=row.id, job_id=row.job_id, deal_id=row.deal_id, task_id=row.task_id,
        archetype=row.archetype, model_id=row.model_id, model_version=row.model_version,
        prompt_template_id=row.prompt_template_id, prompt_hash=row.prompt_hash,
        input_digest=row.input_digest or {}, output=row.output or {},
        confidence=row.confidence, tokens_in=row.tokens_in, tokens_out=row.tokens_out,
        cost_inr=row.cost_inr, latency_ms=row.latency_ms, started_at=row.started_at,
        completed_at=row.completed_at, tool_calls=list(row.tool_calls or []),
        segment_id=row.segment_id, trace_id=row.trace_id, span_id=row.span_id)


def finding_to_domain(row: FindingRow, deal_id: int) -> Finding:
    return Finding(id=row.id, diligence_item_id=row.diligence_item_id, deal_id=deal_id,
                   finding_type=FindingType(row.finding_type), description=row.description,
                   quantified_impact_inr=row.quantified_impact_inr,
                   affects_valuation=bool(row.affects_valuation), raised_by=row.raised_by,
                   raised_at=row.raised_at)


def extraction_to_domain(row: ExtractionRow) -> Extraction:
    return Extraction(
        id=row.id, document_id=row.document_id, version=row.version,
        schema_name=row.schema_name, payload=row.payload or {}, confidence=row.confidence,
        feeds_valuation=bool(row.feeds_valuation), human_verified_by=row.human_verified_by,
        human_verified_at=row.human_verified_at, model_run_id=row.model_run_id,
        created_at=row.created_at)


def signoff_to_domain(row: DealSignoffRow) -> DealSignoff:
    return DealSignoff(id=row.id, deal_id=row.deal_id, signed_by=row.signed_by,
                       note=row.note or "", signed_at=row.signed_at)
