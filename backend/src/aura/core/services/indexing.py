"""The indexing pipeline (phase 2): load -> parse -> chunk -> screen -> embed -> store.

A document is queued on upload, on every new version and on a reindex request. The queue is
its own small table (index_job, one row per document) worked by the worker loop, with the
same reliability rules as agent segments (aura.core.policy.retry_policy):
- a transient failure (the embedding model unreachable, a timeout) is retried with
  exponential backoff, and dead-lettered after max_attempts;
- a permanent failure (unsupported or corrupt file, too many pages) fails at once;
- a claim older than the lease (the worker died) is recovered by the next sweep.
Either way the document shows index_status 'failed' with the reason, and a person can ask
for a reindex.

Chunks are screened for prompt injection here (aura.core.policy.injection_policy): the text
is kept as written but the risk score and matched rules are stored on the chunk, and context
assembly screens and wraps it again before any model sees it.

The new chunks replace the document's previous ones in one transaction: a search never sees
half of a version.
"""
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable

from aura.core.clock import utcnow
from aura.core.domain.audit import AuditEntry
from aura.core.domain.document import Document
from aura.core.domain.enums import Role
from aura.core.domain.errors import NotFound
from aura.core.domain.ingest import EmbedRun, EmbeddingError, IndexJob, StoredChunk
from aura.core.policy.injection_policy import screen
from aura.core.policy.rbac_policy import Capability, require
from aura.core.policy.retry_policy import RetryPolicy, error_text, is_transient
from aura.core.ports.ingest import (ChunkRepository, DocumentIndexState, DocumentParser,
                                    EmbedRunSink, Embedder, IndexQueue)
from aura.core.ports.repositories import AuditRepository, DocumentRepository
from aura.core.services.chunking import ChunkingParams, chunk_document
from aura.core.tracing import current_trace, tracer

DEFAULT_EMBED_BATCH = 16


@dataclass(frozen=True)
class IndexSettings:
    chunking: ChunkingParams = ChunkingParams()
    embed_batch: int = DEFAULT_EMBED_BATCH


class SupersededClaim(Exception):
    """The job was re-queued (a newer version, a reindex) while this run was working."""


def enqueue(doc: Document, actor: str, queue: IndexQueue, state: DocumentIndexState) -> IndexJob:
    """Mark the document pending and queue its current version."""
    trace_id, span_id = current_trace()
    state.set_index_state(doc.id, status="pending", error=None)
    doc.index_status, doc.index_error = "pending", None
    return queue.enqueue(doc.id, doc.deal_id, doc.current_version, actor, trace_id, span_id)


def request_reindex(document_id: int, actor: str, actor_role: Role,
                    documents: DocumentRepository, queue: IndexQueue,
                    state: DocumentIndexState, audit: AuditRepository) -> Document:
    """A person asks for the document to be indexed again (dealmaker, analyst). `documents`
    is the actor's: a document behind a wall they are not on is not found."""
    require(actor_role, Capability.EDIT_DEAL_DATA, "reindex documents")
    doc = documents.get(document_id)
    if doc is None:
        raise NotFound("Document not found")
    enqueue(doc, actor, queue, state)
    audit.append(AuditEntry(id=None, job_id=None, deal_id=doc.deal_id, actor=actor,
                            action="document_reindex_requested", created_at=utcnow(),
                            payload={"document_id": doc.id, "version": doc.current_version}))
    return documents.get(document_id) or doc


def _batches(items: list, size: int):
    size = max(1, size)
    for i in range(0, len(items), size):
        yield items[i:i + size]


def embed_chunks(texts: list[str], embedder: Embedder, runs: EmbedRunSink | None,
                 deal_id: int | None, document_id: int | None,
                 batch: int = DEFAULT_EMBED_BATCH) -> list[list[float]]:
    """Embed in batches; one embed_run row (and one embed.batch span) per batch."""
    vectors: list[list[float]] = []
    for group in _batches(texts, batch):
        started, clock = utcnow(), time.perf_counter()
        error, out = None, None
        with tracer.span("embed.batch", {"gen_ai.operation.name": "embeddings",
                                         "gen_ai.request.model": embedder.model,
                                         "aura.batch_size": len(group)},
                         deal_id=deal_id) as span:
            try:
                out = embedder.embed(group, kind="document")
                if len(out) != len(group):
                    raise EmbeddingError(f"{len(out)} vectors for {len(group)} texts")
                bad = next((len(v) for v in out if len(v) != embedder.dimensions), None)
                if bad is not None:
                    raise EmbeddingError(f"embedding has {bad} dimensions, expected "
                                         f"{embedder.dimensions}")
            except Exception as exc:
                error = error_text(exc, 500)
                raise
            finally:
                if runs is not None:
                    runs.record(EmbedRun(
                        id=None, deal_id=deal_id, document_id=document_id,
                        model=embedder.model, kind="document", batch_size=len(group),
                        input_chars=sum(len(t) for t in group),
                        dimensions=len(out[0]) if out else None,
                        latency_ms=int((time.perf_counter() - clock) * 1000),
                        status="error" if error else "ok", error=error,
                        trace_id=span.trace_id, span_id=span.span_id, created_at=started))
        vectors.extend(out)
    return vectors


def index_document(job: IndexJob, documents: DocumentRepository, read_bytes,
                   parser: DocumentParser, embedder: Embedder, chunks: ChunkRepository,
                   state: DocumentIndexState, audit: AuditRepository,
                   runs: EmbedRunSink | None = None,
                   settings: IndexSettings = IndexSettings(),
                   between: Callable[[], None] | None = None) -> dict:
    """Index the document's current version. `documents` is SYSTEM-scoped but the job only
    ever touches its own document and deal. Raises on failure (the caller decides retry or
    dead letter); returns a summary on success.

    Nothing touches the database between reading the document and writing the chunks:
    `between` (the worker passes session.commit) ends the read transaction, so parsing, OCR
    and embedding (seconds to minutes) never hold a transaction open. The embed_run rows are
    collected and written with the chunks; on failure they ride on the exception
    (`exc.embed_runs`) so the caller can still record them."""
    doc = documents.get(job.document_id)
    if doc is None or doc.deal_id != job.deal_id:
        raise NotFound(f"Document {job.document_id} no longer exists on deal {job.deal_id}")
    if between is not None:
        between()
    collected = _Collect()
    try:
        return _index(job, doc, read_bytes, parser, embedder, chunks, state, audit, runs,
                      settings, collected)
    except Exception as exc:
        try:
            exc.embed_runs = collected.runs
        except AttributeError:  # pragma: no cover - exceptions with __slots__
            pass
        raise


class _Collect:
    def __init__(self):
        self.runs: list[EmbedRun] = []

    def record(self, run: EmbedRun) -> EmbedRun:
        self.runs.append(run)
        return run


def _index(job, doc, read_bytes, parser, embedder, chunks, state, audit, runs, settings,
           collected: "_Collect") -> dict:
    with tracer.span("index.document", {"aura.document_id": doc.id,
                                        "aura.version": doc.current_version,
                                        "aura.index_job_id": job.id},
                     trace_id=job.trace_id, parent_span_id=job.span_id,
                     deal_id=doc.deal_id) as span:
        content = read_bytes(doc.sha256)
        parsed = parser.parse(content, doc.filename)
        drafts = chunk_document(parsed, settings.chunking)
        stored: list[StoredChunk] = []
        flagged = 0
        for d in drafts:
            result = screen(d.text)
            meta = dict(d.meta)
            if d.heading:
                meta["heading"] = d.heading
            meta["risk_score"] = result.risk_score
            if result.matched_rules:
                meta["matched_rules"] = result.matched_rules
                flagged += 1
            stored.append(StoredChunk(id=None, document_id=doc.id, deal_id=doc.deal_id,
                                      version=doc.current_version, chunk_index=d.index,
                                      text=d.text, kind=d.kind, page_from=d.page_from,
                                      page_to=d.page_to, embedding_model=embedder.model,
                                      meta=meta))
        vectors = embed_chunks([c.text for c in stored], embedder, collected, doc.deal_id,
                               doc.id, settings.embed_batch) if stored else []
        for c, v in zip(stored, vectors):
            c.embedding = v
        warnings = list(parsed.warnings)
        if not stored:
            warnings.append("no text found to index")
        if flagged:
            warnings.append(f"{flagged} chunk(s) flagged by prompt-injection screening")
        count = chunks.replace_for_document(doc.id, doc.deal_id, doc.current_version, stored)
        if runs is not None:
            for run in collected.runs:
                runs.record(run)
        now = utcnow()
        state.set_index_state(doc.id, status="indexed", chunk_count=count,
                              ocr_used=parsed.ocr_used, page_count=parsed.page_count,
                              warnings=warnings, error=None, indexed_at=now)
        summary = {"document_id": doc.id, "version": doc.current_version, "chunks": count,
                   "ocr_used": parsed.ocr_used, "page_count": parsed.page_count,
                   "warnings": warnings, "embedding_model": embedder.model,
                   "flagged_chunks": flagged}
        span.set_attributes({"aura.chunks": count, "aura.ocr_used": parsed.ocr_used})
        audit.append(AuditEntry(id=None, job_id=None, deal_id=doc.deal_id, actor="system",
                                action="document_indexed", created_at=now,
                                payload={**summary, "index_job_id": job.id}))
        return summary


def handle_index_failure(job: IndexJob, exc: BaseException, policy: RetryPolicy,
                         queue: IndexQueue, state: DocumentIndexState,
                         audit: AuditRepository, now: datetime | None = None) -> str:
    """Record a failed attempt: 'retry' (transient, attempts left), 'dead_letter' (transient,
    none left) or 'failed' (permanent). The caller has rolled the attempt back."""
    now = now or utcnow()
    error = error_text(exc)
    claimed_by = job.claimed_by
    job.last_error = error
    job.updated_at = now
    if is_transient(exc) and policy.can_retry(job.attempts):
        job.status, job.not_before = "queued", policy.next_run_at(now, job.attempts)
        job.claimed_by = job.claimed_at = None
        if queue.update(job, claimed_by):
            audit.append(AuditEntry(id=None, job_id=None, deal_id=job.deal_id, actor="system",
                                    action="index_retry_scheduled", created_at=now,
                                    payload={"document_id": job.document_id,
                                             "index_job_id": job.id, "attempts": job.attempts,
                                             "error": error,
                                             "not_before": job.not_before.isoformat()}))
        return "retry"
    outcome = "dead_letter" if is_transient(exc) else "failed"
    job.status, job.claimed_by = "dead_letter", None
    if not queue.update(job, claimed_by):
        return "superseded"
    state.set_index_state(job.document_id, status="failed", error=error)
    audit.append(AuditEntry(id=None, job_id=None, deal_id=job.deal_id, actor="system",
                            action="document_index_failed", created_at=now,
                            payload={"document_id": job.document_id, "index_job_id": job.id,
                                     "attempts": job.attempts, "error": error,
                                     "reason": "max_attempts" if outcome == "dead_letter"
                                     else "permanent"}))
    return outcome


def recover_stale(queue: IndexQueue, state: DocumentIndexState, audit: AuditRepository,
                  policy: RetryPolicy, now: datetime | None = None) -> int:
    """Running jobs whose claim outlived the lease: requeue, or dead-letter when spent."""
    now = now or utcnow()
    stale = queue.list_stale_running(now - timedelta(seconds=policy.lease_seconds))
    for job in stale:
        claimed_by = job.claimed_by
        error = (f"Lease expired: claimed by {claimed_by or 'unknown'} and never finished")
        job.last_error, job.updated_at = error, now
        if policy.can_retry(job.attempts):
            job.status, job.not_before, job.claimed_by, job.claimed_at = \
                "queued", None, None, None
            queue.update(job, claimed_by)
        else:
            job.status, job.claimed_by = "dead_letter", None
            if queue.update(job, claimed_by):
                state.set_index_state(job.document_id, status="failed", error=error)
                audit.append(AuditEntry(
                    id=None, job_id=None, deal_id=job.deal_id, actor="system",
                    action="document_index_failed", created_at=now,
                    payload={"document_id": job.document_id, "index_job_id": job.id,
                             "attempts": job.attempts, "error": error,
                             "reason": "lease_expired"}))
    return len(stale)
