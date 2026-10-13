"""Document ingestion: what a parser returns, what the chunker makes of it, what search finds
(phase 2: multi-format parsing, chunking, embeddings and hybrid search)."""
from dataclasses import dataclass, field
from datetime import datetime

from aura.core.domain.errors import DomainError

BLOCK_KINDS = ("text", "table", "heading")
CHUNK_KINDS = ("text", "table")
INDEX_STATUSES = ("pending", "indexed", "failed")
EMBED_KINDS = ("document", "query")


class IngestError(DomainError):
    """A document that cannot be parsed. Permanent: retrying gives the same answer."""


class UnsupportedFormat(IngestError):
    """The file type is not one Aura can read (HTTP 415 on upload)."""


class CorruptDocument(IngestError):
    """The file claims a supported type but cannot be read (damaged, encrypted, empty)."""


class DocumentTooLarge(IngestError):
    """Over max_upload_mb or max_pages (HTTP 413 on upload)."""


class EmbeddingError(Exception):
    """The embedding model answered with something unusable (wrong dimension, bad JSON).
    Not a DomainError: an unreachable model is transient and is retried by the queue."""


@dataclass
class Block:
    """One structural piece of a parsed document. `rows` holds a table's cells (the first
    row is the header, or the first meta['header_rows'] rows); `text` is always the readable
    form used for search. `meta` carries what the parser knows about the block: 'header_rows',
    'columns' (flattened column names of a multi-row header), 'source' ('ocr', 'vlm'),
    'needs_review' (a vision-model number OCR did not confirm), ..."""
    kind: str
    text: str
    page: int | None = None
    rows: list[list[str]] | None = None
    level: int | None = None  # heading level, when known
    meta: dict = field(default_factory=dict)


@dataclass
class ParsedDocument:
    blocks: list[Block]
    metadata: dict = field(default_factory=dict)
    page_count: int | None = None
    ocr_used: bool = False
    warnings: list[str] = field(default_factory=list)
    # Lineage of model calls made while parsing (vision-model page reads), recorded with the
    # document's embedding batches.
    model_runs: list["EmbedRun"] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(b.text for b in self.blocks if b.text)


@dataclass
class ChunkDraft:
    """A chunk before it is embedded and stored."""
    index: int
    text: str
    kind: str = "text"
    page_from: int | None = None
    page_to: int | None = None
    heading: str | None = None
    meta: dict = field(default_factory=dict)


@dataclass
class StoredChunk:
    id: int | None
    document_id: int
    deal_id: int
    version: int
    chunk_index: int
    text: str
    kind: str
    page_from: int | None
    page_to: int | None
    embedding_model: str | None
    meta: dict = field(default_factory=dict)
    embedding: list[float] | None = None
    created_at: datetime | None = None


@dataclass
class ChunkHit:
    """One ranked list's view of a chunk (vector or full text)."""
    chunk_id: int
    document_id: int
    filename: str
    version: int
    chunk_index: int
    text: str
    kind: str
    page_from: int | None
    page_to: int | None
    distance: float | None = None   # cosine distance (vector list)
    fts_score: float | None = None  # ts_rank_cd (full-text list)
    snippet: str | None = None      # ts_headline, matches in ⟦ ⟧


@dataclass
class SearchResult:
    rank: int
    chunk_id: int
    document_id: int
    filename: str
    version: int
    chunk_index: int
    page_from: int | None
    page_to: int | None
    kind: str
    snippet: str
    text: str
    score: float
    scores: dict


@dataclass
class SearchResponse:
    query: str
    k: int
    mode: str  # hybrid | fts_only
    embedding_model: str | None
    took_ms: int
    results: list[SearchResult]
    warnings: list[str] = field(default_factory=list)


@dataclass
class IndexJob:
    """The indexing queue: one row per document (a new version replaces a waiting job)."""
    id: int | None
    document_id: int
    deal_id: int
    version: int
    status: str  # queued | running | done | dead_letter
    attempts: int = 0
    not_before: datetime | None = None
    claimed_by: str | None = None
    claimed_at: datetime | None = None
    last_error: str | None = None
    requested_by: str | None = None
    trace_id: str | None = None
    span_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass
class EmbedRun:
    """Lineage of one embedding batch (embed_run): model, size, latency, outcome."""
    id: int | None
    deal_id: int | None
    document_id: int | None
    model: str
    kind: str
    batch_size: int
    input_chars: int
    dimensions: int | None
    latency_ms: int
    status: str  # ok | error
    error: str | None = None
    trace_id: str | None = None
    span_id: str | None = None
    created_at: datetime | None = None
