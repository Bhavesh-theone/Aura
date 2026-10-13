"""The deal-intake extraction worker: claims an intake whose staged files are all indexed
and runs aura.core.services.intake_extraction on it, never inside an HTTP request.

Reliability is the indexing queue's: the claim is committed at once (FOR UPDATE SKIP
LOCKED), a transient failure (Ollama unreachable, a timeout) is retried with backoff, a
claim older than the lease is recovered by the sweep, and after the last attempt the
extraction still runs - deterministically (identifier regexes, table grids), without the
model - so the person always gets a form to review, with a warning saying why. Nothing holds
a database transaction open while the model thinks: chunks are read and the retrieval done
first, model runs are collected and written with the result, and progress goes out in small
transactions of its own (and as live events to the intake's creator only).
"""
import logging
import os
import socket
import threading
import time
import uuid
from datetime import timedelta

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from aura.config import get_settings
from aura.core.clock import utcnow
from aura.core.domain.audit import AuditEntry
from aura.core.policy.retry_policy import RetryPolicy, error_text, is_transient
from aura.core.ports.events import EventPublisher
from aura.core.ports.orchestrator import RunContext
from aura.core.services import intake as intake_service
from aura.core.services.intake_extraction import ExtractionSettings, run_extraction
from aura.core.services.notifying_audit import NotifyingAudit
from aura.core.services.search import search
from aura.core.tracing import tracer
from aura.data.engine import SessionLocal
from aura.data.repositories.sql import SqlAgentRunRepository, SqlAuditRepository
from aura.data.repositories.sql_ingest import SqlChunkRepository
from aura.data.repositories.sql_intake import SqlIntakeRepository
from aura.data.spans import flush_spans
from aura.data.uow import SqlUnitOfWork
from aura.data.walls import SYSTEM

POLL_SECONDS = 2.0
SWEEP_SECONDS = 60.0
WORKER_ID = f"intake:{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
logger = logging.getLogger(__name__)


def intake_policy() -> RetryPolicy:
    s = get_settings()
    return RetryPolicy(max_attempts=s.intake_max_attempts,
                       base_backoff_seconds=s.intake_backoff_seconds,
                       lease_seconds=s.intake_lease_seconds)


class CollectingRuns:
    """agent_run rows held until the extraction's result is written (or its failure)."""

    def __init__(self):
        self.runs = []

    def record(self, run):
        self.runs.append(run)
        return run


def extractor_factory(recorder):
    """The configured model adapter, or None ('off'). Tests replace this."""
    s = get_settings()
    if s.intake_llm == "off":
        return None
    from aura.agents.llm.intake_extractor import OllamaFieldExtractor
    return OllamaFieldExtractor(recorder, s.ollama_base_url, s.ollama_model,
                                s.intake_llm_timeout_s, s.intake_llm_num_ctx, s.ollama_think)


def embedder_factory():
    from aura.ingest.wiring import query_embedder
    return query_embedder()


def _model_digest() -> str:
    s = get_settings()
    try:
        from aura.agents.llm.ollama_check import model_digest
        return model_digest(s.ollama_base_url, s.ollama_model)
    except Exception:
        return "unknown"


def _publish(events: EventPublisher, intake, stage: str, percent: int, message: str) -> None:
    events.publish("entity_changed", {"kind": "intake", "deal_id": None,
                                      "intake_id": intake.id, "recipient": intake.created_by,
                                      "stage": stage, "percent": percent,
                                      "message": message})


def _set_progress(session: Session, intake_id: int, progress: dict) -> None:
    repo = SqlIntakeRepository(session, SYSTEM)
    intake = repo.get(intake_id)
    if intake is None or intake.extract_status != "running":
        session.rollback()
        return
    intake.progress = {**(intake.progress or {}), **progress}
    repo.save(intake)
    session.commit()


def extract_once(session: Session, events: EventPublisher, worker_id: str = WORKER_ID,
                 extractor=None, embedder=None, policy: RetryPolicy | None = None,
                 extractor_for=None) -> str | None:
    """Claim and run one extraction. Returns 'extracted', 'retry', 'dead_letter',
    'superseded', or None when nothing is ready. `extractor` (a FieldExtractor) or
    `extractor_for(recorder)` replaces the configured model (tests)."""
    s = get_settings()
    policy = policy or intake_policy()
    session.commit()
    repo = SqlIntakeRepository(session, SYSTEM)
    try:
        intake = repo.claim_next_extraction(worker_id, utcnow())
        session.commit()
    except OperationalError:
        session.rollback()
        return None
    if intake is None:
        return None

    runs = CollectingRuns()
    last_attempt = intake.extract_attempts >= policy.max_attempts
    with tracer.span("intake.extract", {"aura.intake_id": intake.id,
                                         "aura.attempt": intake.extract_attempts}) as span:
        context = RunContext(job_id=None, deal_id=None, task_id=None, runs=runs,
                             username=intake.created_by, intake_id=intake.id)
        from aura.agents.llm.recording import RunRecorder
        recorder = RunRecorder(context, s.ollama_model, _model_digest(),
                               max_calls=s.intake_max_llm_calls,
                               max_seconds=s.intake_max_seconds)
        model = extractor if extractor is not None else (
            extractor_for(recorder) if extractor_for else extractor_factory(recorder))
        warnings: list[str] = []
        if model is not None and last_attempt:
            if intake.extract_attempts > 1:
                warnings.append(
                    "The local model failed on every attempt; these fields come from "
                    "the deterministic extractors only")
            model = None
        started = utcnow()
        chunks = repo.chunks(intake.id)
        files = repo.files(intake.id)
        search_repo = SqlChunkRepository(session, SYSTEM, intake_id=intake.id)
        query_embed = embedder if embedder is not None else embedder_factory()
        cache: dict[tuple[str, int], list[int]] = {}

        def retrieve(query: str, k: int) -> list[int]:
            key = (query, k)
            if key not in cache:
                from aura.core.services.search import SearchParams
                try:
                    response = search(0, query[:500], search_repo, query_embed,
                                      SearchParams(k=k, candidates=s.search_candidates,
                                                   rrf_k=s.rrf_k, ef_search=s.hnsw_ef_search))
                    cache[key] = [r.chunk_id for r in response.results]
                finally:
                    session.commit()  # end the read: the model call must not hold it
            return cache[key]

        total = {"groups": 9}

        def progress(stage: str, done: int, n: int, message: str) -> None:
            total["groups"] = max(n, 1)
            percent = 50 + int(48 * done / max(n, 1))
            try:
                _set_progress(session, intake.id, {"stage": stage, "message": message,
                                                   "groups_done": done, "groups_total": n})
            except Exception:
                session.rollback()
            _publish(events, intake, stage, percent, message)

        session.commit()
        _publish(events, intake, "extracting", 50, "Extracting fields")
        try:
            result = run_extraction(
                chunks, retrieve, model, intake_service.schema_for,
                hints=intake.hints,
                settings=ExtractionSettings(threshold=s.intake_confidence_threshold,
                                            top_k=s.intake_top_k,
                                            context_chars=s.intake_context_chars,
                                            injection_threshold=s.injection_risk_threshold),
                progress=progress)
            result.warnings[:0] = warnings
            failed = [d.filename for d in files if d.index_status == "failed"]
            if failed:
                result.warnings.append("Not read (indexing failed): " + ", ".join(failed))
            span.set_attributes({"aura.fields": len(result.fields),
                                 "aura.conflicts": len(result.conflicts),
                                 "aura.llm_groups": len(result.llm_groups)})
        except Exception as exc:
            session.rollback()
            return _failed(session, events, intake, exc, runs, policy, worker_id)

    uow = SqlUnitOfWork(session)
    deferred = uow.defer(events)
    audit = NotifyingAudit(SqlAuditRepository(session, SYSTEM), deferred)
    try:
        repo = SqlIntakeRepository(session, SYSTEM)
        current = repo.hold_extraction(intake.id, worker_id)
        if current is None:
            uow.rollback()
            return "superseded"
        sink = SqlAgentRunRepository(session, SYSTEM)
        for run in runs.runs:
            sink.add(run)
        intake_service.apply_extraction(current, result)
        finished = utcnow()
        current.status = "review"
        current.extract_status, current.extract_error = "done", None
        current.extract_claimed_by = None
        current.extract_meta = {
            **(current.extract_meta or {}), "started_at": started.isoformat(),
            "finished_at": finished.isoformat(), "duration_ms": result.duration_ms,
            "model": getattr(model, "model", None), "llm_used": result.llm_used,
            "llm_groups": result.llm_groups, "warnings": result.warnings,
            "model_runs": len(runs.runs)}
        current.progress = {"stage": "ready", "message": "Ready for review",
                            "groups_done": total["groups"], "groups_total": total["groups"]}
        repo.save(current)
        audit.append(AuditEntry(id=None, job_id=None, deal_id=None, actor="system",
                                action="intake_extracted", created_at=finished,
                                payload={"intake_id": current.id,
                                         "recipient": current.created_by,
                                         "fields": len(result.fields),
                                         "conflicts": len(result.conflicts),
                                         "llm_used": result.llm_used,
                                         "model_runs": len(runs.runs),
                                         "duration_ms": result.duration_ms}))
        uow.commit()
    except Exception:
        uow.rollback()
        raise
    flush_spans(session)
    _publish(events, current, "ready", 100, "Ready for review")
    return "extracted"


def _failed(session: Session, events: EventPublisher, intake, exc: Exception, runs,
            policy: RetryPolicy, worker_id: str) -> str:
    """Retry a transient failure with backoff; a permanent one (or no attempts left)
    dead-letters. The model runs of the failed attempt are still recorded."""
    logger.warning("intake %s extraction failed: %s", intake.id, exc)
    now = utcnow()
    uow = SqlUnitOfWork(session)
    deferred = uow.defer(events)
    audit = NotifyingAudit(SqlAuditRepository(session, SYSTEM), deferred)
    repo = SqlIntakeRepository(session, SYSTEM)
    try:
        current = repo.hold_extraction(intake.id, worker_id)
        if current is None:
            uow.rollback()
            return "superseded"
        sink = SqlAgentRunRepository(session, SYSTEM)
        for run in runs.runs:
            sink.add(run)
        error = error_text(exc, 1000)
        current.extract_error, current.extract_claimed_by = error, None
        if is_transient(exc) and policy.can_retry(current.extract_attempts):
            current.extract_status = "queued"
            current.extract_not_before = policy.next_run_at(now, current.extract_attempts)
            outcome = "retry"
        else:
            current.extract_status = "dead_letter"
            outcome = "dead_letter"
        current.progress = {**(current.progress or {}), "message":
                            "The model is unavailable; retrying" if outcome == "retry"
                            else "Extraction failed"}
        repo.save(current)
        audit.append(AuditEntry(id=None, job_id=None, deal_id=None, actor="system",
                                action="intake_extraction_failed", created_at=now,
                                payload={"intake_id": current.id,
                                         "recipient": current.created_by,
                                         "attempts": current.extract_attempts,
                                         "outcome": outcome, "error": error[:300]}))
        uow.commit()
    except Exception:
        uow.rollback()
        raise
    flush_spans(session)
    return outcome


def sweep_stale_extractions(session: Session, policy: RetryPolicy | None = None) -> int:
    policy = policy or intake_policy()
    repo = SqlIntakeRepository(session, SYSTEM)
    stale = repo.stale_extractions(utcnow() - timedelta(seconds=policy.lease_seconds))
    for intake in stale:
        intake.extract_status = "queued" if policy.can_retry(intake.extract_attempts) \
            else "dead_letter"
        intake.extract_claimed_by = None
        intake.extract_error = "Lease expired: the worker stopped before finishing"
        repo.save(intake)
    session.commit()
    return len(stale)


def _loop(events: EventPublisher, stop: threading.Event) -> None:
    last_sweep: float | None = None
    while not stop.is_set():
        outcome = None
        try:
            with SessionLocal() as session:
                if last_sweep is None or time.monotonic() - last_sweep >= SWEEP_SECONDS:
                    last_sweep = time.monotonic()
                    if sweep_stale_extractions(session):
                        logger.warning("recovered orphaned intake extraction(s)")
                outcome = extract_once(session, events)
        except Exception:
            logger.exception("intake worker iteration failed")
        if outcome is None:
            stop.wait(POLL_SECONDS)


def start_intake_worker(events: EventPublisher, stop: threading.Event) -> None:
    threading.Thread(target=_loop, args=(events, stop), daemon=True,
                     name="aura-intake").start()
