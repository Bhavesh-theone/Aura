


from aura.core.clock import utcnow
from aura.core.domain.audit import AuditEntry
from aura.core.domain.enums import (AssignmentMode, HandoffDirection, HandoffTrigger,
                                    JobStatus, SegmentStatus)
from aura.core.domain.extraction import CONFIDENCE_GATE
from aura.core.domain.handoff import Handoff
from aura.core.domain.segment import ProposedAction
from aura.core.policy.gate_policy import (DEFAULT_MATERIALITY_CAP_INR, classify,
                                          exceeds_materiality, requires_approval)
from aura.core.policy.handoff_policy import APPROVING_DECISIONS, build_gate_package
from aura.core.ports.events import EventPublisher
from aura.core.ports.orchestrator import AgentRunSink, Orchestrator, RunContext
from aura.core.ports.repositories import (AuditRepository, DocumentRepository,
                                          ExtractionRepository, HandoffRepository,
                                          JobRepository, SegmentRepository, TaskRepository)
from aura.core.ports.uow import UnitOfWork
from aura.core.services.extractions import record_extraction
from aura.core.services.handoffs import continue_job, create_handoff

CONFIDENCE_THRESHOLD = CONFIDENCE_GATE


def _trigger(action: ProposedAction, cap_inr: int) -> HandoffTrigger:
    if exceeds_materiality(action.materiality_inr, cap_inr):
        return HandoffTrigger.MATERIALITY_GATE
    confidence = action.arguments.get("confidence")
    if action.tool in ("classify_document", "extract_financials") \
            and isinstance(confidence, (int, float)) and confidence < CONFIDENCE_THRESHOLD:
        return HandoffTrigger.CONFIDENCE_BELOW_THRESHOLD
    return HandoffTrigger.POLICY_REQUIRED


def _earlier_directive(handoffs: HandoffRepository, deal_id: int | None,
                       task_type: str) -> Handoff | None:
    """The newest resolved handoff on this deal whose directive said not to revisit this
    kind of decision (new_constraints.do_not_revisit lists the task type)."""
    if deal_id is None:
        return None
    for h in handoffs.list_all(resolved=True):
        constraints = (h.directive or {}).get("new_constraints") or {}
        if h.deal_id == deal_id and task_type in (constraints.get("do_not_revisit") or []):
            return h
    return None


def _extraction_action(segment, extraction_id: int, proposal) -> ProposedAction:
    doc = segment.context_in.get("document") or {}
    return ProposedAction(
        tool="extract_financials", category=classify("extract_financials"),
        arguments={"extraction_id": extraction_id, "document_id": doc.get("id"),
                   "filename": doc.get("filename"), "schema_name": proposal.schema_name,
                   "payload": proposal.payload, "confidence": proposal.confidence},
        summary=f"Verify the figures read from {doc.get('filename', 'the document')} "
                f"(confidence {proposal.confidence:.2f})")


def run_segment(
    segment_id: int,
    orchestrator: Orchestrator,
    jobs: JobRepository,
    segments: SegmentRepository,
    tasks: TaskRepository,
    handoffs: HandoffRepository,
    audit: AuditRepository,
    events: EventPublisher,
    runs: AgentRunSink,
    uow: UnitOfWork,
    materiality_cap_inr: int = DEFAULT_MATERIALITY_CAP_INR,
    extractions: ExtractionRepository | None = None,
    documents: DocumentRepository | None = None,
) -> None:
    """Run one segment to completion or to a gate. Never blocks on a human.

    Two transactions: the RUNNING mark commits first so progress is visible while the model
    works; everything the outcome writes (segment, job, task, handoff, audit) commits as one.
    """
    segment = segments.get(segment_id)
    if segment is None:
        raise ValueError(f"segment {segment_id} not found")

    job = jobs.get(segment.job_id)
    now = utcnow()

    segment.status = SegmentStatus.RUNNING
    segment.started_at = now
    segments.update(segment)
    job.status = JobStatus.RUNNING
    jobs.update(job)
    uow.commit()

    run_context = RunContext(job_id=job.id, deal_id=job.deal_id, task_id=None, runs=runs,
                             username=job.created_by)
    try:
        result = orchestrator.run(segment.context_in, run_context)
        ended = utcnow()
        segment.context_out = result.context_out
        segment.ended_at = ended

        action = result.proposed_action
        if result.extraction is not None:
            if extractions is None or documents is None:
                raise ValueError("extraction results need the extraction and document stores")
            document = documents.get((segment.context_in.get("document") or {}).get("id"))
            if document is None:
                raise ValueError("the extraction's document is not on this deal")
            saved = record_extraction(result.extraction, document, "system", job.id,
                                      extractions, audit, now=ended)
            # A confident extraction is simply recorded; it still feeds nothing until a
            # person verifies it. A doubtful one also goes to a person as a handoff.
            if result.extraction.confidence < CONFIDENCE_THRESHOLD:
                action = _extraction_action(segment, saved.id, result.extraction)

        if action is not None and requires_approval(action.category, action.materiality_inr,
                                                    materiality_cap_inr):
            segment.status = SegmentStatus.AWAITING_APPROVAL
            segments.update(segment)
            earlier = _earlier_directive(handoffs, job.deal_id, action.tool)
            if earlier is not None:
                decision = earlier.directive["decision"]
                audit.append(AuditEntry(
                    id=None, job_id=job.id, deal_id=job.deal_id, actor="system",
                    action="handoff_skipped_per_directive", created_at=ended,
                    payload={"task_type": action.tool, "source_handoff_id": earlier.id,
                             "decision": decision,
                             "approved": decision in APPROVING_DECISIONS}))
                continue_job(job.id, decision in APPROVING_DECISIONS, jobs, segments)
            else:
                create_handoff(
                    deal_id=job.deal_id, job_id=job.id, task_type=action.tool,
                    assignment_mode=AssignmentMode.HUMAN_REQUIRED,
                    direction=HandoffDirection.BOT_TO_HUMAN,
                    trigger=_trigger(action, materiality_cap_inr),
                    context_package=build_gate_package(action, ended, materiality_cap_inr),
                    directive=None, materiality_inr=action.materiality_inr, actor="system",
                    tasks=tasks, handoffs=handoffs, audit=audit, events=events, now=ended)
                job.status = JobStatus.AWAITING_APPROVAL
                jobs.update(job)
        else:
            segment.status = SegmentStatus.DONE
            segments.update(segment)
            job.status = JobStatus.COMPLETE
            job.result = result.context_out
            jobs.update(job)
            audit.append(AuditEntry(id=None, job_id=job.id, deal_id=job.deal_id,
                                    actor="system", action="job_completed",
                                    payload={"segment_id": segment.id}, created_at=ended))
            events.publish("job_complete", {"job_id": job.id, "deal_id": job.deal_id})
    except Exception as exc:
        # Nothing the failed attempt wrote may survive; then record the failure itself.
        uow.rollback()
        segment.status = SegmentStatus.FAILED
        segment.ended_at = utcnow()
        segments.update(segment)
        job.status = JobStatus.FAILED
        jobs.update(job)
        audit.append(AuditEntry(id=None, job_id=job.id, deal_id=job.deal_id, actor="system",
                                action="segment_failed",
                                payload={"segment_id": segment.id, "error": str(exc)},
                                created_at=utcnow()))
        events.publish("job_failed", {"job_id": job.id, "deal_id": job.deal_id})
    uow.commit()
