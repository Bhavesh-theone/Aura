from dataclasses import dataclass
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


@dataclass
class DocumentVersion:
    document_id: int
    version: int
    sha256: str
    byte_size: int
    uploaded_by: str
    uploaded_at: datetime
