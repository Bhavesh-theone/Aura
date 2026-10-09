"""Chunks, the indexing queue and embedding lineage on PostgreSQL + pgvector.

Every query runs under the session's row-level security (aura.viewer); the user-scoped
repositories also filter by wall membership in SQL (defence in depth, aura.data.walls).
"""
from datetime import datetime

from sqlalchemy import Integer, Text, cast, delete, func, literal, select, text, update
from sqlalchemy.dialects.postgresql import TSQUERY, insert
from sqlalchemy.orm import Session

from aura.core.clock import utcnow
from aura.core.domain.ingest import ChunkHit, EmbedRun, IndexJob, StoredChunk
from aura.core.services.search import HIGHLIGHT_END, HIGHLIGHT_START
from aura.data.models.tables import DocChunkRow, DocumentRow, EmbedRunRow, IndexJobRow
from aura.data.walls import Viewer, bind_viewer, walled

_SET = text("SELECT set_config(:k, :v, true)")
HEADLINE_OPTIONS = (f"StartSel={HIGHLIGHT_START}, StopSel={HIGHLIGHT_END}, MaxWords=45, "
                    "MinWords=15, MaxFragments=2, FragmentDelimiter=\" … \"")


def _chunk(row: DocChunkRow) -> StoredChunk:
    return StoredChunk(id=row.id, document_id=row.document_id, deal_id=row.deal_id,
                       version=row.version, chunk_index=row.chunk_index, text=row.text,
                       kind=row.kind, page_from=row.page_from, page_to=row.page_to,
                       embedding_model=row.embedding_model, meta=dict(row.meta or {}),
                       created_at=row.created_at)


class SqlChunkRepository:
    def __init__(self, session: Session, viewer: Viewer):
        self.s, self.viewer = session, bind_viewer(session, viewer)

    def replace_for_document(self, document_id: int, deal_id: int, version: int,
                             chunks: list[StoredChunk]) -> int:
        """Delete the document's chunks and insert these, in the caller's transaction."""
        self.s.execute(delete(DocChunkRow).where(DocChunkRow.document_id == document_id))
        self.s.add_all([DocChunkRow(
            document_id=document_id, deal_id=deal_id, version=version,
            chunk_index=c.chunk_index, text=c.text, kind=c.kind, page_from=c.page_from,
            page_to=c.page_to, embedding=c.embedding, embedding_model=c.embedding_model,
            meta=c.meta or {}) for c in chunks])
        self.s.flush()
        return len(chunks)

    def _scoped(self, stmt):
        return walled(stmt, self.viewer, DocChunkRow.deal_id)

    def list_for_document(self, document_id: int, offset: int = 0,
                          limit: int = 50) -> tuple[int, list[StoredChunk]]:
        base = self._scoped(select(DocChunkRow).where(DocChunkRow.document_id == document_id))
        total = self.s.scalar(select(func.count()).select_from(base.subquery())) or 0
        rows = self.s.scalars(base.order_by(DocChunkRow.chunk_index)
                              .offset(max(0, offset)).limit(max(1, limit))).all()
        return total, [_chunk(r) for r in rows]

    def document_text(self, document_id: int, limit_chars: int = 20_000) -> str | None:
        """The indexed text of the document, chunk by chunk (overlaps included)."""
        rows = self.s.scalars(self._scoped(
            select(DocChunkRow.text).where(DocChunkRow.document_id == document_id)
            .order_by(DocChunkRow.chunk_index))).all()
        out, size = [], 0
        for t in rows:
            out.append(t)
            size += len(t)
            if size >= limit_chars:
                break
        return "\n\n".join(out)[:limit_chars] if out else None

    def _hit_columns(self):
        return (DocChunkRow.id, DocChunkRow.document_id, DocumentRow.filename,
                DocChunkRow.version, DocChunkRow.chunk_index, DocChunkRow.text,
                DocChunkRow.kind, DocChunkRow.page_from, DocChunkRow.page_to)

    def _current(self, stmt, deal_id: int):
        """Chunks of the deal's documents, current version only."""
        return self._scoped(stmt.join(DocumentRow, DocumentRow.id == DocChunkRow.document_id)
                            .where(DocChunkRow.deal_id == deal_id,
                                   DocChunkRow.version == DocumentRow.current_version))

    def vector_search(self, deal_id: int, vector: list[float], limit: int,
                      ef_search: int = 80) -> list[ChunkHit]:
        self.s.execute(_SET, {"k": "hnsw.ef_search", "v": str(max(limit, ef_search))})
        # The deal filter is applied after the HNSW scan: keep scanning until enough rows
        # of this deal are found (pgvector 0.8 iterative scans), in exact distance order.
        self.s.execute(_SET, {"k": "hnsw.iterative_scan", "v": "strict_order"})
        distance = DocChunkRow.embedding.cosine_distance(vector)
        stmt = self._current(select(*self._hit_columns(), distance.label("distance"))
                             .where(DocChunkRow.embedding.is_not(None)), deal_id)
        rows = self.s.execute(stmt.order_by(distance, DocChunkRow.id).limit(limit)).all()
        return [ChunkHit(chunk_id=r.id, document_id=r.document_id, filename=r.filename,
                         version=r.version, chunk_index=r.chunk_index, text=r.text,
                         kind=r.kind, page_from=r.page_from, page_to=r.page_to,
                         distance=float(r.distance)) for r in rows]

    def text_search(self, deal_id: int, query: str, limit: int) -> list[ChunkHit]:
        """websearch_to_tsquery over the chunk's tsvector. Chunks matching every term come
        first; then chunks matching any term (the same query with AND turned into OR), each
        group by ts_rank_cd. The snippet is a ts_headline with matches in ⟦ ⟧."""
        all_terms = func.websearch_to_tsquery("english", query)
        any_term = cast(func.replace(cast(all_terms, Text), " & ", " | "), TSQUERY)
        rank = func.ts_rank_cd(DocChunkRow.tsv, any_term)
        every = DocChunkRow.tsv.op("@@")(all_terms)
        inner = self._current(
            select(*self._hit_columns(), rank.label("score"),
                   cast(every, Integer).label("every"))
            .where(DocChunkRow.tsv.op("@@")(any_term)), deal_id) \
            .order_by(every.desc(), rank.desc(), DocChunkRow.id).limit(limit).subquery()
        headline = func.ts_headline("english", inner.c.text, any_term,
                                    literal(HEADLINE_OPTIONS))
        rows = self.s.execute(select(inner, headline.label("snippet"))
                              .order_by(inner.c.every.desc(), inner.c.score.desc(),
                                        inner.c.id)).all()
        return [ChunkHit(chunk_id=r.id, document_id=r.document_id, filename=r.filename,
                         version=r.version, chunk_index=r.chunk_index, text=r.text,
                         kind=r.kind, page_from=r.page_from, page_to=r.page_to,
                         fts_score=float(r.score) + float(r.every),
                         snippet=" ".join((r.snippet or "").split())) for r in rows]


def _job(row: IndexJobRow) -> IndexJob:
    return IndexJob(id=row.id, document_id=row.document_id, deal_id=row.deal_id,
                    version=row.version, status=row.status, attempts=row.attempts,
                    not_before=row.not_before, claimed_by=row.claimed_by,
                    claimed_at=row.claimed_at, last_error=row.last_error,
                    requested_by=row.requested_by, trace_id=row.trace_id,
                    span_id=row.span_id, created_at=row.created_at,
                    updated_at=row.updated_at)


class SqlIndexQueue:
    """index_job. Enqueueing is done in the uploader's (or reindexer's) transaction, so it
    runs under their RLS scope; claiming and finishing are the worker's (SYSTEM)."""

    def __init__(self, session: Session, viewer: Viewer):
        self.s, self.viewer = session, bind_viewer(session, viewer)

    def enqueue(self, document_id: int, deal_id: int, version: int, requested_by: str,
                trace_id: str | None, span_id: str | None) -> IndexJob:
        now = utcnow()
        values = {"version": version, "status": "queued", "attempts": 0, "not_before": None,
                  "claimed_by": None, "claimed_at": None, "last_error": None,
                  "requested_by": requested_by, "trace_id": trace_id, "span_id": span_id,
                  "updated_at": now}
        stmt = insert(IndexJobRow).values(document_id=document_id, deal_id=deal_id,
                                          **values)
        stmt = stmt.on_conflict_do_update(index_elements=[IndexJobRow.document_id],
                                          set_=values).returning(IndexJobRow.id)
        job_id = self.s.execute(stmt).scalar_one()
        return _job(self.s.get(IndexJobRow, job_id, populate_existing=True))

    def claim_next(self, worker_id: str, now: datetime) -> IndexJob | None:
        candidate = (select(IndexJobRow.id)
                     .where(IndexJobRow.status == "queued",
                            (IndexJobRow.not_before.is_(None))
                            | (IndexJobRow.not_before <= now))
                     .order_by(IndexJobRow.id).limit(1)
                     .with_for_update(skip_locked=True).scalar_subquery())
        stmt = (update(IndexJobRow)
                .where(IndexJobRow.id == candidate, IndexJobRow.status == "queued")
                .values(status="running", claimed_by=worker_id, claimed_at=now,
                        attempts=IndexJobRow.attempts + 1, updated_at=now)
                .returning(IndexJobRow.id)
                .execution_options(synchronize_session=False))
        job_id = self.s.execute(stmt).scalar_one_or_none()
        if job_id is None:
            return None
        return _job(self.s.get(IndexJobRow, job_id, populate_existing=True))

    def get(self, job_id: int) -> IndexJob | None:
        row = self.s.get(IndexJobRow, job_id, populate_existing=True)
        return _job(row) if row else None

    def for_document(self, document_id: int) -> IndexJob | None:
        row = self.s.scalars(walled(select(IndexJobRow).where(
            IndexJobRow.document_id == document_id), self.viewer, IndexJobRow.deal_id)).first()
        return _job(row) if row else None

    def update(self, job: IndexJob, expected_claimed_by: str | None) -> bool:
        stmt = (update(IndexJobRow)
                .where(IndexJobRow.id == job.id, IndexJobRow.status == "running",
                       IndexJobRow.claimed_by.is_not_distinct_from(expected_claimed_by))
                .values(status=job.status, attempts=job.attempts, not_before=job.not_before,
                        claimed_by=job.claimed_by, claimed_at=job.claimed_at,
                        last_error=job.last_error, updated_at=job.updated_at or utcnow())
                .execution_options(synchronize_session=False))
        return self.s.execute(stmt).rowcount == 1

    def list_stale_running(self, claimed_before: datetime) -> list[IndexJob]:
        rows = self.s.scalars(select(IndexJobRow).where(
            IndexJobRow.status == "running",
            (IndexJobRow.claimed_at.is_(None)) | (IndexJobRow.claimed_at < claimed_before))
            .order_by(IndexJobRow.id)).all()
        return [_job(r) for r in rows]

    def hold(self, job_id: int, claimed_by: str) -> bool:
        row = self.s.execute(select(IndexJobRow.status, IndexJobRow.claimed_by)
                             .where(IndexJobRow.id == job_id).with_for_update()).first()
        return row is not None and row.status == "running" and row.claimed_by == claimed_by

    def counts(self) -> dict[str, int]:
        rows = self.s.execute(walled(select(IndexJobRow.status, func.count())
                                     .group_by(IndexJobRow.status), self.viewer,
                                     IndexJobRow.deal_id)).all()
        return {status: n for status, n in rows}


class SqlEmbedRunSink:
    def __init__(self, session: Session):
        self.s = session

    def record(self, run: EmbedRun) -> EmbedRun:
        row = EmbedRunRow(deal_id=run.deal_id, document_id=run.document_id, model=run.model,
                          kind=run.kind, batch_size=run.batch_size,
                          input_chars=run.input_chars, dimensions=run.dimensions,
                          latency_ms=run.latency_ms, status=run.status, error=run.error,
                          trace_id=run.trace_id, span_id=run.span_id,
                          created_at=run.created_at)
        self.s.add(row)
        self.s.flush()
        run.id = row.id
        return run
