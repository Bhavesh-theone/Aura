from typing import Callable

from aura.core.clock import utcnow
from aura.core.domain.audit import AuditEntry
from aura.core.domain.enums import (AssignmentMode, HandoffDirection, HandoffTrigger,
                                    JobStatus, SegmentStatus)
from aura.core.domain.errors import HandoffRejected
from aura.core.domain.extraction import CONFIDENCE_GATE
from aura.core.domain.handoff import Handoff
from aura.core.domain.harness import LEVEL_AUTONOMOUS, LEVEL_DISABLED
from aura.core.domain.segment import ProposedAction
from aura.core.policy.gate_policy import (DEFAULT_MATERIALITY_CAP_INR, classify,
                                          exceeds_materiality, requires_approval)
from aura.core.policy.handoff_policy import APPROVING_DECISIONS, build_gate_package
from aura.core.policy.injection_policy import DEFAULT_THRESHOLD
from aura.core.policy.retry_policy import RetryPolicy
from aura.core.ports.events import EventPublisher
from aura.core.ports.orchestrator import AgentRunSink, Orchestrator, RunContext
from aura.core.ports.repositories import (AgentRunRepository, AuditRepository,
                                          AutonomyRepository, DocumentRepository,
                                          ExtractionRepository, HandoffRepository,
                                          JobRepository, SegmentRepository, TaskRepository)
from aura.core.ports.uow import UnitOfWork
from aura.core.services.autonomy import ensure_enabled, level_of
from aura.core.services.extractions import record_extraction
from aura.core.services.handoffs import continue_job, create_handoff
from aura.core.services.outbound import OutboundService
from aura.core.services.segment_reliability import handle_segment_failure
from aura.core.tracing import tracer

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


def _extraction_action(context: dict, extraction_id: int, proposal) -> ProposedAction:
    doc = context.get("document") or {}
    return ProposedAction(
        tool="extract_financials", category=classify("extract_financials"),
        arguments={"extraction_id": extraction_id, "document_id": doc.get("id"),
                   "filename": doc.get("filename"), "schema_name": proposal.schema_name,
                   "payload": proposal.payload, "confidence": proposal.confidence},
        summary=f"Verify the figures read from {doc.get('filename', 'the document')} "
                f"(confidence {proposal.confidence:.2f})")


def untrusted_summary(context_in: dict, context_out: dict | None,
                      threshold: float) -> dict | None:
    """The screening record when the text the agent read crossed the injection threshold
    (the assembled context, or tool output the agent saw during the run), else None."""
    screening = dict(context_in.get("screening") or {})
    tool_hits = list((context_out or {}).get("tool_output_screening") or [])
    items = list(screening.get("items") or []) + tool_hits
    risk = max([screening.get("risk_score") or 0.0]
               + [h.get("risk_score") or 0.0 for h in tool_hits])
    if risk < threshold:
        return None
    rules = sorted(set(screening.get("matched_rules") or [])
                   | {r for h in tool_hits for r in h.get("matched_rules") or []})
    # A person already looked at a result built on this text and let the job carry on.
    acknowledged = set(context_in.get("untrusted_acknowledged") or [])
    if acknowledged and set(rules) <= acknowledged:
        return None
    return {"risk_score": risk, "matched_rules": rules, "threshold": threshold,
            "items": items}


def _still_ours(segments: SegmentRepository, segment_id: int, claimed_by: str | None,
                attempts: int) -> bool:
    hold = getattr(segments, "hold_claim", None)
    return True if hold is None else hold(segment_id, claimed_by, attempts)


def _discard_stale(segment, job, claimed_by, attempts, segments, audit, uow) -> str:
    """The segment was recovered or re-claimed while this worker ran it: the late result is
    thrown away (its model runs stay on record) and the discard is audited."""
    uow.rollback()
    current = segments.get(segment.id)
    audit.append(AuditEntry(
        id=None, job_id=job.id, deal_id=job.deal_id, actor="system",
        action="stale_result_discarded", created_at=utcnow(),
        payload={"segment_id": segment.id, "claimed_by": claimed_by, "attempts": attempts,
                 "current": {"status": current.status.value if current else None,
                             "claimed_by": current.claimed_by if current else None,
                             "attempts": current.attempts if current else None}}))
    uow.commit()
    return "stale"


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
    retry_policy: RetryPolicy | None = None,
    run_links: AgentRunRepository | None = None,
    autonomy: AutonomyRepository | None = None,
    refresh_context: Callable[[dict], dict] | None = None,
    injection_threshold: float = DEFAULT_THRESHOLD,
    outbound: OutboundService | None = None,
) -> str:
    """Run one segment to completion or to a gate. Never blocks on a human.

    Two transactions: the RUNNING mark commits first so progress is visible while the model
    works; everything the outcome writes (segment, job, task, handoff, audit) commits as one.

    Before the model runs: the capability's autonomy level is consulted (level 0 fails a
    first segment), and the context is re-assembled as the job's user (refresh_context), so
    documents are re-read and wall changes since submit apply.

    After it runs: if the segment's claim changed meanwhile (recovered or re-claimed), the
    result is discarded ('stale_result_discarded'). Text that looked like a prompt injection
    forces a handoff (trigger 'untrusted_content', audited 'injection_suspected'). At autonomy
    level 1 a confident extraction also goes to a person.

    Outbound email (`outbound`): a draft_email job resumed after its handoff was approved
    runs the outbound step first (checks, then the Gmail MCP server; it commits its own rows so
    nothing is locked while Gmail answers) and its outcome lands in the job's result. A
    draft_email handoff is annotated with the recipient and what approving will do.

    A failure rolls the outcome back and is then classified (retry_policy): a transient one
    requeues the segment with backoff or, out of attempts, dead-letters it; anything else
    fails it. A HandoffRejected keeps its 'handoff_rejected' audit row before failing.
    Returns 'done', 'awaiting_approval', 'retry', 'dead_letter', 'failed' or 'stale'.
    """
    segment = segments.get(segment_id)
    if segment is None:
        raise ValueError(f"segment {segment_id} not found")
    job = jobs.get(segment.job_id)
    with tracer.span("segment.run", {"aura.segment_id": segment.id, "aura.job_id": job.id,
                                     "aura.seq": segment.seq},
                     trace_id=getattr(job, "trace_id", None),
                     parent_span_id=getattr(job, "span_id", None),
                     deal_id=job.deal_id) as span:
        outcome = _run(segment, job, orchestrator, jobs, segments, tasks, handoffs, audit,
                       events, runs, uow, materiality_cap_inr, extractions, documents,
                       retry_policy, run_links, autonomy, refresh_context, injection_threshold,
                       outbound)
        span.set("aura.outcome", outcome)
        return outcome


def _run(segment, job, orchestrator, jobs, segments, tasks, handoffs, audit, events, runs, uow,
         materiality_cap_inr, extractions, documents, retry_policy, run_links, autonomy,
         refresh_context, injection_threshold, outbound=None) -> str:
    now = utcnow()
    claimed_by, attempts = segment.claimed_by, segment.attempts

    segment.status = SegmentStatus.RUNNING
    segment.started_at = now
    segments.update(segment)
    job.status = JobStatus.RUNNING
    jobs.update(job)
    uow.commit()

    capability = segment.context_in.get("capability")
    outcome = "done"
    held = False  # the claim was confirmed and is locked until this transaction ends
    try:
        level = level_of(autonomy, capability)
        if level <= LEVEL_DISABLED and segment.seq == 1:
            ensure_enabled(autonomy, capability)  # raises CapabilityDisabled: permanent
        # A person approved this job's email: the outbound step runs before anything else and
        # is idempotent per handoff, so a retried segment never sends twice.
        outbound_result = outbound.execute_after_approval(job) \
            if outbound is not None and outbound.applies(segment) else None
        context = refresh_context(segment.context_in) if refresh_context is not None \
            else segment.context_in
        screening = context.get("screening") or {}
        run_context = RunContext(
            job_id=job.id, deal_id=job.deal_id, task_id=None, runs=runs,
            username=job.created_by, segment_id=segment.id,
            notes={"screening": {k: screening.get(k) for k in
                                 ("risk_score", "matched_rules", "flagged")}}
            if screening else None)
        result = orchestrator.run(context, run_context)
        if not _still_ours(segments, segment.id, claimed_by, attempts):
            return _discard_stale(segment, job, claimed_by, attempts, segments, audit, uow)
        held = True
        ended = utcnow()
        segment.context_out = result.context_out
        segment.ended_at = ended

        untrusted = untrusted_summary(context, result.context_out, injection_threshold)
        notes: list[str] = []
        action = result.proposed_action
        if result.extraction is not None:
            if extractions is None or documents is None:
                raise ValueError("extraction results need the extraction and document stores")
            document = documents.get((context.get("document") or {}).get("id"))
            if document is None:
                raise ValueError("the extraction's document is not on this deal")
            saved = record_extraction(result.extraction, document, "system", job.id,
                                      extractions, audit, now=ended)
            # A confident extraction is simply recorded; it still feeds nothing until a
            # person verifies it. A doubtful one also goes to a person as a handoff, and so
            # does every one while the capability is supervised (level 1) or the text was
            # suspicious.
            confident = result.extraction.confidence >= CONFIDENCE_THRESHOLD
            if not confident or level < LEVEL_AUTONOMOUS or untrusted:
                action = _extraction_action(context, saved.id, result.extraction)
                if confident and level < LEVEL_AUTONOMOUS:
                    notes.append(f"Autonomy for {capability} is at level {level}: every "
                                 "result goes to a person.")
        if untrusted and action is None:
            # Even a result that needs no approval is held when its input was suspicious.
            action = ProposedAction(
                tool="review_agent_output", category=classify("review_agent_output"),
                arguments={"draft": (result.context_out or {}).get("draft")},
                summary="Review an agent result built on suspicious text")
        if untrusted:
            segment.context_out = {**(segment.context_out or {}), "proposal_made": True,
                                   "untrusted_acknowledged": untrusted["matched_rules"]}
            audit.append(AuditEntry(
                id=None, job_id=job.id, deal_id=job.deal_id, actor="system",
                action="injection_suspected", created_at=ended,
                payload={"segment_id": segment.id, "risk_score": untrusted["risk_score"],
                         "matched_rules": untrusted["matched_rules"],
                         "sources": [i.get("source") for i in untrusted["items"]
                                     if i.get("matched_rules")]}))

        if action is not None and (untrusted or requires_approval(
                action.category, action.materiality_inr, materiality_cap_inr)):
            segment.status = SegmentStatus.AWAITING_APPROVAL
            segments.update(segment)
            earlier = None if untrusted else _earlier_directive(handoffs, job.deal_id,
                                                                action.tool)
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
                if outbound is not None:
                    action = outbound.describe_draft(action)
                trigger = HandoffTrigger.UNTRUSTED_CONTENT if untrusted \
                    else _trigger(action, materiality_cap_inr)
                handoff = create_handoff(
                    deal_id=job.deal_id, job_id=job.id, task_type=action.tool,
                    assignment_mode=AssignmentMode.HUMAN_REQUIRED,
                    direction=HandoffDirection.BOT_TO_HUMAN, trigger=trigger,
                    context_package=build_gate_package(action, ended, materiality_cap_inr,
                                                       untrusted=untrusted, notes=notes),
                    directive=None, materiality_inr=action.materiality_inr, actor="system",
                    tasks=tasks, handoffs=handoffs, audit=audit, events=events, now=ended)
                if run_links is not None:  # the segment's model runs now belong to a task
                    run_links.link_task(segment.id, handoff.task_id)
                job.status = JobStatus.AWAITING_APPROVAL
                jobs.update(job)
            outcome = "awaiting_approval"
        else:
            segment.status = SegmentStatus.DONE
            segments.update(segment)
            job.status = JobStatus.COMPLETE
            job.result = result.context_out if outbound_result is None \
                else {**(result.context_out or {}), "outbound": outbound_result}
            jobs.update(job)
            audit.append(AuditEntry(id=None, job_id=job.id, deal_id=job.deal_id,
                                    actor="system", action="job_completed",
                                    payload={"segment_id": segment.id}, created_at=ended))
            events.publish("job_complete", {"job_id": job.id, "deal_id": job.deal_id})
    except Exception as exc:
        if isinstance(exc, HandoffRejected):
            # The refusal's audit row is the point (persist_writes): keep it, then fail.
            uow.commit()
        else:
            # Nothing the failed attempt wrote may survive; then record the failure itself.
            uow.rollback()
        if not held and not _still_ours(segments, segment.id, claimed_by, attempts):
            return _discard_stale(segment, job, claimed_by, attempts, segments, audit, uow)
        outcome = handle_segment_failure(segment, job, exc, retry_policy or RetryPolicy(),
                                         segments, jobs, audit, events, utcnow())
    uow.commit()
    return outcome
