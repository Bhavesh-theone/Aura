"""The indexing queue's worker step (aura.core.services.indexing does the work).

Runs in its own daemon thread next to the segment loop, so a long document (OCR, hundreds of
chunks to embed) never holds up agent work. Each claim is committed at once (FOR UPDATE SKIP
LOCKED: two workers never take the same job); the pipeline's writes are committed together
only if the claim is still ours, otherwise rolled back (a newer version was queued while we
worked, and the next claim indexes that).
"""
import logging
import os
import socket
import threading
import time
import uuid

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from aura.config import get_settings
from aura.core.clock import utcnow
from aura.core.policy.retry_policy import RetryPolicy
from aura.core.ports.events import EventPublisher
from aura.core.services.chunking import ChunkingParams
from aura.core.services.indexing import (IndexSettings, SupersededClaim,
                                         handle_index_failure, index_document, recover_stale)
from aura.core.services.notifying_audit import NotifyingAudit
from aura.data.engine import SessionLocal
from aura.data.repositories.sql import SqlAuditRepository
from aura.data.repositories.sql_deals import SqlDocumentRepository
from aura.data.repositories.sql_ingest import SqlChunkRepository, SqlEmbedRunSink, SqlIndexQueue
from aura.data.spans import flush_spans
from aura.data.uow import SqlUnitOfWork
from aura.data.walls import SYSTEM

POLL_SECONDS = 2.0
SWEEP_SECONDS = 60.0
WORKER_ID = f"index:{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
logger = logging.getLogger(__name__)


def index_policy() -> RetryPolicy:
    s = get_settings()
    return RetryPolicy(max_attempts=s.index_max_attempts,
                       base_backoff_seconds=s.index_backoff_seconds,
                       lease_seconds=s.index_lease_seconds)


def index_settings() -> IndexSettings:
    s = get_settings()
    return IndexSettings(chunking=ChunkingParams(s.chunk_target_tokens, s.chunk_overlap_tokens),
                         embed_batch=s.embed_batch)


def parser_factory():
    from aura.ingest.parsers import FormatRegistryParser
    return FormatRegistryParser()


def embedder_factory():
    """The configured embedder (tests swap in FakeEmbedder)."""
    from aura.ingest.embedder import make_embedder
    return make_embedder()


def store_factory():
    from aura.worker import runner
    return runner.store_factory()


def index_once(session: Session, events: EventPublisher, worker_id: str = WORKER_ID,
               parser=None, embedder=None, store=None, policy: RetryPolicy | None = None
               ) -> str | None:
    """Claim and run one queued index job. Returns the outcome ('indexed', 'retry',
    'dead_letter', 'failed', 'superseded') or None when the queue is empty."""
    session.commit()
    queue = SqlIndexQueue(session, SYSTEM)
    try:
        job = queue.claim_next(worker_id, utcnow())
        session.commit()
    except OperationalError:
        session.rollback()
        logger.warning("index claim lost a lock race; will try again", exc_info=True)
        return None
    if job is None:
        return None

    uow = SqlUnitOfWork(session)
    deferred = uow.defer(events)
    audit = NotifyingAudit(SqlAuditRepository(session, SYSTEM), deferred)
    documents = SqlDocumentRepository(session, SYSTEM)
    store = store or store_factory()
    try:
        index_document(job, documents, store.read_bytes, parser or parser_factory(),
                       embedder or embedder_factory(), SqlChunkRepository(session, SYSTEM),
                       documents, audit, SqlEmbedRunSink(session), index_settings(),
                       between=session.commit)
        if not queue.hold(job.id, worker_id):
            raise SupersededClaim(f"index job {job.id} was re-queued while it ran")
        job.status, job.last_error, job.updated_at = "done", None, utcnow()
        queue.update(job, worker_id)
        uow.commit()
        flush_spans(session)
        return "indexed"
    except SupersededClaim:
        uow.rollback()
        return "superseded"
    except Exception as exc:
        uow.rollback()
        logger.warning("indexing document %s failed: %s", job.document_id, exc)
        uow = SqlUnitOfWork(session)
        deferred = uow.defer(events)
        audit = NotifyingAudit(SqlAuditRepository(session, SYSTEM), deferred)
        try:
            outcome = handle_index_failure(job, exc, policy or index_policy(),
                                           SqlIndexQueue(session, SYSTEM),
                                           SqlDocumentRepository(session, SYSTEM), audit)
            sink = SqlEmbedRunSink(session)  # lineage of the failed attempt's batches
            for run in getattr(exc, "embed_runs", []):
                sink.record(run)
            uow.commit()
        except Exception:
            uow.rollback()
            raise
        flush_spans(session)
        return outcome


def sweep_stale_index_jobs(session: Session, events: EventPublisher,
                           policy: RetryPolicy | None = None) -> int:
    uow = SqlUnitOfWork(session)
    try:
        deferred = uow.defer(events)
        count = recover_stale(SqlIndexQueue(session, SYSTEM),
                              SqlDocumentRepository(session, SYSTEM),
                              NotifyingAudit(SqlAuditRepository(session, SYSTEM), deferred),
                              policy or index_policy())
        uow.commit()
    except Exception:
        uow.rollback()
        raise
    return count


def _loop(events: EventPublisher, stop: threading.Event) -> None:
    last_sweep: float | None = None
    parser, embedder = parser_factory(), embedder_factory()
    while not stop.is_set():
        outcome = None
        try:
            with SessionLocal() as session:
                if last_sweep is None or time.monotonic() - last_sweep >= SWEEP_SECONDS:
                    last_sweep = time.monotonic()
                    recovered = sweep_stale_index_jobs(session, events)
                    if recovered:
                        logger.warning("recovered %d orphaned index job(s)", recovered)
                outcome = index_once(session, events, parser=parser, embedder=embedder)
        except Exception:
            logger.exception("index worker iteration failed")
        if outcome is None:
            stop.wait(POLL_SECONDS)


def start_index_worker(events: EventPublisher) -> threading.Event:
    stop = threading.Event()
    threading.Thread(target=_loop, args=(events, stop), daemon=True,
                     name="aura-indexer").start()
    return stop
