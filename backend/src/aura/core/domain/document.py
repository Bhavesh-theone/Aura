from dataclasses import dataclass, field
from datetime import datetime

from aura.core.domain.enums import DocClass


@dataclass
class Document:
    id: int | None
    deal_id: int
    doc_class: DocClass
    filename: str
    sha256: str
    byte_size: int
    current_version: int
    contains_upsi: bool
    sensitivity: int
    uploaded_by: str
    uploaded_at: datetime
    class_confirmed: bool = False
    is_executed: bool = False
    # Indexing (migration 0002): pending until the index queue has parsed, chunked and
    # embedded the current version; failed keeps the reason in index_error.
    index_status: str = "pending"
    indexed_at: datetime | None = None
    chunk_count: int = 0
    ocr_used: bool = False
    page_count: int | None = None
    index_warnings: list[str] = field(default_factory=list)
    index_error: str | None = None


@dataclass
class DocumentVersion:
    document_id: int
    version: int
    sha256: str
    byte_size: int
    uploaded_by: str
    uploaded_at: datetime
