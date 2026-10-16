"""The deal intake (phase 3): a deal being assembled from uploaded documents before it
exists, the chunks it reads them through, and what extraction proposes for each field."""
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Citation:
    document_id: int
    filename: str
    page_from: int | None
    page_to: int | None
    chunk_id: int
    quote: str

    def as_dict(self) -> dict:
        return {"document_id": self.document_id, "filename": self.filename,
                "page_from": self.page_from, "page_to": self.page_to,
                "chunk_id": self.chunk_id, "quote": self.quote[:200]}


@dataclass
class Candidate:
    """One proposal for a field: from a regex, a table grid or the model."""
    key: str
    value: object
    confidence: float
    source: str                     # regex | table | llm
    citations: list[Citation] = field(default_factory=list)
    note: str | None = None

    @property
    def document_ids(self) -> set[int]:
        return {c.document_id for c in self.citations}


@dataclass
class Intake:
    """A deal being assembled before it exists (deal_intake). `fields` maps a field key to
    its record ({value, auto_value, confidence, source, citations, accepted, edited, error,
    note, conflict_id}); `conflicts` lists disagreements a person must resolve."""
    id: int | None
    created_by: str
    status: str = "draft"            # draft | processing | review | confirmed | discarded
    transaction_class: str | None = None
    fields: dict = field(default_factory=dict)
    conflicts: list = field(default_factory=list)
    confirmed_deal_id: int | None = None
    hints: dict = field(default_factory=dict)
    external_id: str | None = None
    progress: dict = field(default_factory=dict)
    extract_status: str = "idle"     # idle | queued | running | done | dead_letter
    extract_attempts: int = 0
    extract_not_before: datetime | None = None
    extract_claimed_by: str | None = None
    extract_claimed_at: datetime | None = None
    extract_error: str | None = None
    extract_meta: dict = field(default_factory=dict)
    trace_id: str | None = None
    span_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass
class StagedChunk:
    chunk_id: int
    document_id: int
    filename: str
    page_from: int | None
    page_to: int | None
    kind: str
    text: str
    meta: dict = field(default_factory=dict)

    def cite(self, quote: str) -> "Citation":
        return Citation(self.document_id, self.filename, self.page_from, self.page_to,
                        self.chunk_id, " ".join(quote.split())[:200])
