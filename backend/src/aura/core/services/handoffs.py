"""Tasks and handoffs (SOSPE section 6.12 and 9.5): where agents hand decisions to humans."""
from datetime import datetime


from aura.core.clock import utcnow
from aura.core.domain.audit import AuditEntry
from aura.core.domain.enums import (AssignmentMode, DocClass, HandoffDirection, HandoffStatus,
                                    HandoffTrigger, JobStatus, Role, SegmentStatus,
                                    TaskStatus)
from aura.core.domain.errors import Conflict, HandoffRejected, NotFound, RuleViolation
from aura.core.domain.handoff import Handoff, Task
from aura.core.domain.segment import Segment
from aura.core.policy.handoff_policy import (APPROVING_DECISIONS, option_ids,
                                             validate_bot_to_human, validate_directive)
from aura.core.policy.rbac_policy import (require_any_resolve_handoff,
                                          require_resolve_handoff)
from aura.core.ports.events import EventPublisher
from aura.core.ports.repositories import (AuditRepository, DealRepository, DocumentRepository,
                                          ExtractionRepository, HandoffRepository,
                                          JobRepository, SegmentRepository, TaskRepository)
from aura.core.services.extractions import apply_verification


def create_handoff(
    *,
    deal_id: int | None,
    job_id: int | None,
    task_type: str,
    assignment_mode: AssignmentMode,
    direction: HandoffDirection,
    trigger: HandoffTrigger,
    context_package: dict,
    directive: dict | None,
    materiality_inr: int | None,
    actor: str,
    tasks: TaskRepository,
    handoffs: HandoffRepository,
    audit: AuditRepository,
    events: EventPublisher,
    deals: DealRepository | None = None,
    now: datetime | None = None,
) -> Handoff:
    """Validate and store a task with its handoff. Raises RuleViolation (422) when a
    bot-to-human package lacks decision_required / if_you_do_nothing, or a human-to-bot
    handoff lacks a complete directive."""
    now = now or utcnow()
    if deals is not None and deal_id is not None and deals.get(deal_id) is None:
        raise NotFound("Deal not found")

    escalate_at = None
    try:
        if direction is HandoffDirection.BOT_TO_HUMAN:
            escalate_at = validate_bot_to_human(context_package)
            status = TaskStatus.REVIEW
        else:
            if not isinstance(context_package, dict):
                raise RuleViolation("context_package is required and must be an object")
            validate_directive(directive)
            status = TaskStatus.ASSIGNED
    except RuleViolation as exc:
        # The refusal is itself a record; HandoffRejected tells the unit of work to keep it.
        audit.append(AuditEntry(id=None, job_id=job_id, deal_id=deal_id, actor=actor,
                                action="handoff_rejected", created_at=now,
                                payload={"reason": str(exc), "task_type": task_type,
                                         "direction": direction.value,
                                         "trigger": trigger.value}))
        raise HandoffRejected(str(exc)) from None

    task = tasks.add(Task(id=None, deal_id=deal_id, job_id=job_id, task_type=task_type,
                          assignment_mode=assignment_mode, status=status,
                          materiality_inr=materiality_inr, created_at=now))
    handoff = handoffs.add(Handoff(
        id=None, task_id=task.id, deal_id=deal_id, direction=direction, trigger=trigger,
        context_package=context_package, directive=directive, status=HandoffStatus.OPEN,
        auto_escalate_at=escalate_at, created_at=now, job_id=job_id, task_type=task_type))
    audit.append(AuditEntry(id=None, job_id=job_id, deal_id=deal_id, actor=actor,
                            action="handoff_created", created_at=now,
                            payload={"handoff_id": handoff.id, "task_id": task.id,
                                     "task_type": task_type, "direction": direction.value,
                                     "trigger": trigger.value}))
    events.publish("handoff_created", {"handoff_id": handoff.id, "job_id": job_id,
                                       "deal_id": deal_id})
    return handoff


def _apply_classification(handoff: Handoff, decision: str, documents: DocumentRepository) -> None:
    """A human has looked at the agent's class proposal: confirm it, or keep the current
    class. Either way the class is now human-confirmed."""
    args = (handoff.context_package.get("proposed_action") or {}).get("arguments") or {}
    doc_id = args.get("document_id")
    doc = documents.get(doc_id) if isinstance(doc_id, int) else None
    if doc is None:
        return
    if decision == "confirm":
        try:
            chosen = DocClass(args.get("proposed_class"))
        except ValueError:
            raise RuleViolation("The proposed document class is not a valid class") from None
    else:
        chosen = doc.doc_class
    documents.update_classification(doc.id, chosen, True)


def continue_job(job_id: int, approved: bool, jobs: JobRepository,
                  segments: SegmentRepository) -> None:
    """Exactly what approving or rejecting an approval used to do."""
    job = jobs.get(job_id)
    waiting = [s for s in segments.list_for_job(job_id)
               if s.status is SegmentStatus.AWAITING_APPROVAL]
    if job is None or not waiting:
        return
    segment = waiting[-1]
    segment.status = SegmentStatus.DONE
    segments.update(segment)
    if approved:
        segments.add(Segment(id=None, job_id=job.id, seq=segment.seq + 1,
                             status=SegmentStatus.QUEUED,
                             context_in=dict(segment.context_out or {}),
                             context_out=None, started_at=None, ended_at=None))
        job.status = JobStatus.PENDING
    else:
        job.status = JobStatus.REJECTED
    jobs.update(job)


def _apply_extraction(handoff: Handoff, decision: str, actor: str,
                      extractions: ExtractionRepository | None, audit: AuditRepository,
                      now: datetime) -> None:
    """A person looked at a low-confidence extraction. Verifying lets it feed valuation;
    discarding leaves it as it is, never feeding."""
    if decision != "verify" or extractions is None:
        return
    args = (handoff.context_package.get("proposed_action") or {}).get("arguments") or {}
    extraction_id = args.get("extraction_id")
    extraction = extractions.get(extraction_id) if isinstance(extraction_id, int) else None
    if extraction is None or extraction.human_verified_by is not None:
        return
    apply_verification(extraction, actor, handoff.deal_id, extractions, audit, now)


def resolve_handoff(
    handoff_id: int,
    directive: dict,
    actor: str,
    actor_role: Role,
    jobs: JobRepository,
    segments: SegmentRepository,
    tasks: TaskRepository,
    handoffs: HandoffRepository,
    documents: DocumentRepository,
    audit: AuditRepository,
    events: EventPublisher,
    now: datetime | None = None,
    extractions: ExtractionRepository | None = None,
) -> Handoff:
    """Record a human directive. Approving (or confirming) lets the job carry on;
    anything else ends it. Resolving twice is a Conflict."""
    now = now or utcnow()
    require_any_resolve_handoff(actor_role)
    handoff = handoffs.get(handoff_id)
    if handoff is None:
        raise NotFound("Handoff not found")
    if handoff.status is HandoffStatus.RESOLVED:
        raise Conflict(f"Handoff {handoff_id} is already resolved")

    require_resolve_handoff(actor_role, handoff.trigger)
    try:
        validate_directive(directive)
        decision = directive["decision"]
        if handoff.direction is HandoffDirection.BOT_TO_HUMAN \
                and decision not in option_ids(handoff.context_package):
            raise RuleViolation("directive.decision must be one of the offered option ids")
    except RuleViolation as exc:
        audit.append(AuditEntry(id=None, job_id=handoff.job_id, deal_id=handoff.deal_id,
                                actor=actor, action="handoff_rejected", created_at=now,
                                payload={"reason": str(exc), "handoff_id": handoff.id,
                                         "task_type": handoff.task_type,
                                         "stage": "resolve"}))
        raise HandoffRejected(str(exc)) from None

    task = tasks.get(handoff.task_id)
    approved = decision in APPROVING_DECISIONS
    if task.task_type == "classify_document":
        _apply_classification(handoff, decision, documents)
    elif task.task_type == "extract_financials":
        _apply_extraction(handoff, decision, actor, extractions, audit, now)
    if task.job_id is not None:
        continue_job(task.job_id, approved, jobs, segments)

    task.status = TaskStatus.DONE if approved else TaskStatus.CANCELLED
    tasks.update(task)
    handoff.directive = directive
    handoff.status = HandoffStatus.RESOLVED
    handoff.resolved_by, handoff.resolved_at = actor, now
    handoffs.update(handoff)

    audit.append(AuditEntry(id=None, job_id=task.job_id, deal_id=handoff.deal_id, actor=actor,
                            action="handoff_resolved", created_at=now,
                            payload={"handoff_id": handoff.id, "task_id": task.id,
                                     "decision": decision, "approved": approved,
                                     "resolved_by": actor}))
    events.publish("handoff_resolved", {"handoff_id": handoff.id, "job_id": task.job_id,
                                        "deal_id": handoff.deal_id, "approved": approved})
    return handoff


def escalate_overdue(handoffs: HandoffRepository, audit: AuditRepository,
                     events: EventPublisher, now: datetime | None = None) -> int:
    """Mark open handoffs past their auto_escalate_at as escalated. Returns how many."""
    now = now or utcnow()
    overdue = handoffs.list_overdue(now)
    for h in overdue:
        h.status = HandoffStatus.ESCALATED
        handoffs.update(h)
        audit.append(AuditEntry(id=None, job_id=h.job_id, deal_id=h.deal_id, actor="system",
                                action="handoff_escalated", created_at=now,
                                payload={"handoff_id": h.id,
                                         "auto_escalate_at": h.auto_escalate_at.isoformat()}))
        events.publish("handoff_escalated", {"handoff_id": h.id, "job_id": h.job_id,
                                             "deal_id": h.deal_id})
    return len(overdue)
