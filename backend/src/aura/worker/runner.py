import functools
import logging
import os
import socket
import threading
import time
import uuid
from typing import Protocol

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from aura.config import get_settings
from aura.core.clock import utcnow
from aura.core.domain.audit import AuditEntry
from aura.core.policy.retry_policy import RetryPolicy
from aura.core.ports.events import EventPublisher
from aura.core.ports.orchestrator import Orchestrator
from aura.core.services.notifying_audit import NotifyingAudit
from aura.core.services.handoffs import escalate_overdue
from aura.core.services.autonomy import DemotionRules, apply_demotions
from aura.core.services.context_assembly import ContextLimits, assemble_context
from aura.core.services.run_segment import run_segment
from aura.core.services.segment_reliability import (defer_for_budget, recover_stale_segments,
                                                    start_of_utc_day)
from aura.data.engine import SessionLocal
from aura.data.filestore import LocalFileStore
from aura.data.spans import flush_spans
from aura.data.repositories.sql_harness import SqlAutonomyRepository, SqlEvalRepository
from aura.data.repositories.sql import (SqlAgentRunRepository, SqlAuditRepository,
                                        SqlHandoffRepository, SqlJobRepository,
                                        SqlSegmentRepository, SqlTaskRepository)
from aura.data.repositories.sql_deals import SqlDocumentRepository, SqlExtractionRepository
from aura.data.run_sink import SqlAgentRunSink
from aura.data.uow import SqlUnitOfWork
from aura.data.verify_audit import default_anchor_path, refresh_anchor
from aura.data.walls import SYSTEM

POLL_SECONDS = 2.0
ANCHOR_REFRESH_SECONDS = 60.0
WORKER_ID = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
logger = logging.getLogger(__name__)


class Selection(Protocol):
    orchestrator: Orchestrator
    fallback_reason: str | None


class OrchestratorSelector(Protocol):
    """Chooses the orchestrator for each segment (see aura.agents.factory)."""
    def select(self) -> Selection: ...
    def invalidate(self) -> None: ...


def retry_policy() -> RetryPolicy:
    s = get_settings()
    return RetryPolicy(max_attempts=s.segment_max_attempts,
                       base_backoff_seconds=s.segment_backoff_seconds,
                       lease_seconds=s.segment_lease_seconds)


def store_factory():
    """Where document text is read from (tests point this at their temporary store)."""
    return LocalFileStore()


def context_limits() -> ContextLimits:
    s = get_settings()
    return ContextLimits(max_chars=s.max_context_chars, excerpt_chars=s.context_excerpt_chars,
                         retrieval_top_k=s.retrieval_top_k,
                         injection_threshold=s.injection_risk_threshold)


def demotion_rules() -> DemotionRules:
    s = get_settings()
    return DemotionRules(max_override_rate=s.autonomy_max_override_rate,
                         min_decisions=s.autonomy_min_decisions,
                         window_days=s.autonomy_window_days,
                         include_stub_evals=s.autonomy_counts_stub_evals)


def _choose(orchestrator) -> tuple[Orchestrator, str | None]:
    """A fixed orchestrator, or one picked per segment by a selector."""
    if hasattr(orchestrator, "select"):
        selection = orchestrator.select()
        return selection.orchestrator, selection.fallback_reason
    return orchestrator, None


def run_once(session: Session, orchestrator: Orchestrator | OrchestratorSelector,
             events: EventPublisher, materiality_cap_inr: int | None = None,
             worker_id: str = WORKER_ID) -> bool:
    """Claim and run one queued segment. Returns True if work was done.

    The worker acts for the system, so its repositories are unscoped (SYSTEM): it carries
    out decisions that were already made behind the walls.

    The claim is one atomic UPDATE, committed at once. Then, in order: the daily model
    budget (spent: the segment is deferred to tomorrow), the orchestrator for this segment
    (Ollama down: the stub, audited as 'orchestrator_fallback'), and the run itself.
    """
    settings = get_settings()
    session.commit()  # the claim must open its own transaction (see claim_next_queued)
    segments = SqlSegmentRepository(session)
    try:
        claimed = segments.claim_next_queued(worker_id, utcnow())
        session.commit()
    except OperationalError:
        session.rollback()
        logger.warning("segment claim lost a lock race; will try again", exc_info=True)
        return False
    if claimed is None:
        return False

    uow = SqlUnitOfWork(session)
    events = uow.defer(events)
    jobs = SqlJobRepository(session, SYSTEM)
    audit = NotifyingAudit(SqlAuditRepository(session, SYSTEM), events)
    runs = SqlAgentRunRepository(session, SYSTEM)
    cap = materiality_cap_inr if materiality_cap_inr is not None \
        else settings.materiality_cap_inr
    try:
        now = utcnow()
        used = runs.count_since(start_of_utc_day(now))
        if used >= settings.max_llm_calls_per_day:
            job = jobs.get(claimed.job_id)
            defer_for_budget(claimed, job, used, settings.max_llm_calls_per_day, segments,
                             jobs, audit, events, now)
            uow.commit()
            return True

        chosen, fallback_reason = _choose(orchestrator)
        if fallback_reason is not None:
            job = jobs.get(claimed.job_id)
            audit.append(AuditEntry(
                id=None, job_id=claimed.job_id, deal_id=job.deal_id if job else None,
                actor="system", action="orchestrator_fallback", created_at=now,
                payload={"segment_id": claimed.id, "model_id": "stub",
                         "reason": fallback_reason}))
            uow.commit()

        # Context is re-read as the job's user, so their walls (as they are now) apply to
        # what the model sees, not the worker's SYSTEM scope.
        owner = jobs.get(claimed.job_id)
        viewer = (owner.created_by or "") if owner is not None else ""
        refresh = functools.partial(assemble_context,
                                    documents=SqlDocumentRepository(session, viewer),
                                    store=store_factory(), limits=context_limits())
        outcome = run_segment(
            segment_id=claimed.id,
            orchestrator=chosen,
            jobs=jobs,
            segments=segments,
            tasks=SqlTaskRepository(session, SYSTEM),
            handoffs=SqlHandoffRepository(session, SYSTEM),
            audit=audit,
            events=events,
            runs=SqlAgentRunSink(session),
            uow=uow,
            materiality_cap_inr=cap,
            extractions=SqlExtractionRepository(session, SYSTEM),
            documents=SqlDocumentRepository(session, SYSTEM),
            retry_policy=retry_policy(),
            run_links=runs,
            autonomy=SqlAutonomyRepository(session),
            refresh_context=refresh,
            injection_threshold=settings.injection_risk_threshold,
        )
        if outcome in ("retry", "dead_letter") and hasattr(orchestrator, "invalidate"):
            orchestrator.invalidate()  # the model may be gone: check again next segment
        flush_spans(session)  # segment.run ends after the outcome's commit
    except Exception:
        uow.rollback()
        raise
    return True


def sweep_escalations(session: Session, events: EventPublisher) -> int:
    """Escalate open handoffs whose auto_escalate_at has passed."""
    uow = SqlUnitOfWork(session)
    try:
        deferred = uow.defer(events)
        count = escalate_overdue(SqlHandoffRepository(session, SYSTEM),
                                 NotifyingAudit(SqlAuditRepository(session, SYSTEM), deferred),
                                 deferred)
        uow.commit()
    except Exception:
        uow.rollback()
        raise
    return count


def sweep_stale_segments(session: Session, events: EventPublisher,
                         policy: RetryPolicy | None = None) -> int:
    """Requeue (or dead-letter) RUNNING segments whose claim outlived the lease."""
    uow = SqlUnitOfWork(session)
    try:
        deferred = uow.defer(events)
        count = recover_stale_segments(
            SqlSegmentRepository(session), SqlJobRepository(session, SYSTEM),
            NotifyingAudit(SqlAuditRepository(session, SYSTEM), deferred), deferred,
            policy or retry_policy())
        uow.commit()
    except Exception:
        uow.rollback()
        raise
    return count


def sweep_autonomy(session: Session, events: EventPublisher) -> list[dict]:
    """Demote capabilities whose latest eval failed or whose override rate is too high."""
    uow = SqlUnitOfWork(session)
    try:
        deferred = uow.defer(events)
        changes = apply_demotions(SqlAutonomyRepository(session), SqlEvalRepository(session),
                                  SqlHandoffRepository(session, SYSTEM),
                                  NotifyingAudit(SqlAuditRepository(session, SYSTEM), deferred),
                                  demotion_rules())
        uow.commit()
    except Exception:
        uow.rollback()
        raise
    for change in changes:
        logger.warning("autonomy demoted: %s", change)
    return changes


def refresh_audit_anchor() -> None:
    """Keep the anchor close to the audit head, so tail deletion is caught soon after."""
    with SessionLocal() as session:
        result = refresh_anchor(session, default_anchor_path())
    if not result.ok:
        logger.error("AUDIT VERIFICATION FAILED: %s", result.message)


def _loop(orchestrator, events: EventPublisher, stop: threading.Event) -> None:
    last_anchor = time.monotonic()
    last_autonomy: float | None = None
    while not stop.is_set():
        interval = get_settings().autonomy_check_interval_seconds
        if interval > 0 and (last_autonomy is None
                             or time.monotonic() - last_autonomy >= interval):
            last_autonomy = time.monotonic()
            try:
                with SessionLocal() as session:
                    sweep_autonomy(session, events)
            except Exception:
                logger.exception("autonomy sweep failed")
        did_work = False
        with SessionLocal() as session:
            try:
                sweep_escalations(session, events)
                recovered = sweep_stale_segments(session, events)
                if recovered:
                    logger.warning("recovered %d orphaned segment(s)", recovered)
                did_work = run_once(session, orchestrator, events)
            except Exception:
                logger.exception("worker iteration failed")
        if time.monotonic() - last_anchor >= ANCHOR_REFRESH_SECONDS:
            last_anchor = time.monotonic()
            try:
                refresh_audit_anchor()
            except Exception:
                logger.exception("audit anchor refresh failed")
        if not did_work:
            stop.wait(POLL_SECONDS)


def start_worker(orchestrator, events: EventPublisher) -> threading.Event:
    """Start the segment loop in a daemon thread. Returns its stop event.

    `orchestrator` is a fixed Orchestrator or a selector that picks one per segment. The
    first iteration sweeps stale segments, so a crash's orphans are recovered at startup."""
    stop = threading.Event()
    threading.Thread(target=_loop, args=(orchestrator, events, stop), daemon=True).start()
    return stop
