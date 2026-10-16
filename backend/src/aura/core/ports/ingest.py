"""Ports for ingestion: parsing, embedding, chunk storage and the indexing queue. Adapters
live outside core (aura.ingest, aura.data)."""
from datetime import datetime
from typing import Protocol, runtime_checkable

from aura.core.domain.ingest import (ChunkHit, EmbedRun, IndexJob, ParsedDocument,
                                     StoredChunk)


@runtime_checkable
class DocumentParser(Protocol):
    def parse(self, content: bytes, filename: str, mime: str | None = None) -> ParsedDocument:
        """Blocks of text, tables and headings with their pages. Raises UnsupportedFormat,
        CorruptDocument or DocumentTooLarge (all IngestError, permanent)."""
        ...


@runtime_checkable
class Embedder(Protocol):
    model: str
    dimensions: int

    def embed(self, texts: list[str], kind: str = "document") -> list[list[float]]:
        """One vector per text. kind is 'document' (chunks) or 'query' (search input)."""
        ...


class EmbedRunSink(Protocol):
    def record(self, run: EmbedRun) -> EmbedRun: ...


class ChunkRepository(Protocol):
    def replace_for_document(self, document_id: int, deal_id: int | None, version: int,
                             chunks: list[StoredChunk]) -> int:
        """Delete every chunk of the document and insert these, in one transaction."""
        ...
    def list_for_document(self, document_id: int, offset: int = 0,
                          limit: int = 50) -> tuple[int, list[StoredChunk]]: ...
    def vector_search(self, deal_id: int, vector: list[float], limit: int,
                      ef_search: int) -> list[ChunkHit]: ...
    def text_search(self, deal_id: int, query: str, limit: int) -> list[ChunkHit]: ...


class IndexQueue(Protocol):
    def enqueue(self, document_id: int, deal_id: int | None, version: int,
                requested_by: str, trace_id: str | None, span_id: str | None,
                intake_id: int | None = None) -> IndexJob:
        """Queue (or re-queue) the document's indexing; one row per document."""
        ...
    def claim_next(self, worker_id: str, now: datetime) -> IndexJob | None: ...
    def get(self, job_id: int) -> IndexJob | None: ...
    def update(self, job: IndexJob, expected_claimed_by: str | None) -> bool:
        """Write the job's state only while it is still running under that claim; False
        when someone re-queued it meanwhile (the write is skipped)."""
        ...
    def list_stale_running(self, claimed_before: datetime) -> list[IndexJob]: ...
    def hold(self, job_id: int, claimed_by: str) -> bool:
        """Lock the job row; True while it is still running under this claim."""
        ...


class DocumentIndexState(Protocol):
    """Writes the index_* columns of a document (SYSTEM scope: the queue's own work)."""
    def set_index_state(self, document_id: int, *, status: str,
                        chunk_count: int | None = None, ocr_used: bool | None = None,
                        page_count: int | None = None, warnings: list[str] | None = None,
                        error: str | None = None, indexed_at: datetime | None = None) -> None: ...
