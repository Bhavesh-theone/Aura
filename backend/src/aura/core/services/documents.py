


from aura.core.clock import utcnow
from aura.core.domain.audit import AuditEntry
from aura.core.domain.document import Document, DocumentVersion
from aura.core.domain.enums import DocClass, Role
from aura.core.domain.errors import NotFound, RuleViolation
from aura.core.policy.rbac_policy import Capability, require
from aura.core.ports.repositories import (AuditRepository, DealRepository,
                                          DocumentRepository, FileStore)

UPSI_SENSITIVITY = 4


def upload_document(
    deal_id: int,
    filename: str,
    content: bytes,
    doc_class: DocClass,
    contains_upsi: bool,
    sensitivity: int,
    actor: str,
    actor_role: Role,
    deals: DealRepository,
    documents: DocumentRepository,
    store: FileStore,
    audit: AuditRepository,
) -> Document:
    """Upload a document. The same filename on the same deal adds a version to the existing
    document instead of a new document; a new version is not executed until a person says
    so again."""
    require(actor_role, Capability.EDIT_DEAL_DATA, "upload documents")
    if deals.get(deal_id) is None:
        raise NotFound("Deal not found")
    if not 1 <= sensitivity <= 4:
        raise RuleViolation("sensitivity must be 1-4")
    if contains_upsi:
        sensitivity = UPSI_SENSITIVITY
    now = utcnow()
    sha = store.put(content)
    existing = documents.find_by_filename(deal_id, filename)
    if existing is None:
        doc = documents.add(Document(id=None, deal_id=deal_id, doc_class=doc_class,
                                     filename=filename, sha256=sha, byte_size=len(content),
                                     current_version=1, contains_upsi=contains_upsi,
                                     sensitivity=sensitivity, uploaded_by=actor,
                                     uploaded_at=now))
    else:
        doc = documents.add_version(existing.id, sha, len(content), actor, now)
    audit.append(AuditEntry(id=None, job_id=None, deal_id=deal_id, actor=actor,
                            action="document_uploaded", created_at=now,
                            payload={"document_id": doc.id, "sha256": sha,
                                     "doc_class": doc.doc_class.value,
                                     "version": doc.current_version}))
    return doc


def _get(document_id: int, documents: DocumentRepository) -> Document:
    doc = documents.get(document_id)
    if doc is None:
        raise NotFound("Document not found")
    return doc


def open_document(document_id: int, actor: str, documents: DocumentRepository,
                  audit: AuditRepository) -> Document:
    """Fetch a document for download; the access is logged and audited."""
    doc = _get(document_id, documents)
    documents.log_access(document_id, actor, "download")
    audit.append(AuditEntry(id=None, job_id=None, deal_id=doc.deal_id, actor=actor,
                            action="document_downloaded",
                            created_at=utcnow(),
                            payload={"document_id": doc.id, "version": doc.current_version}))
    return doc


def view_document(document_id: int, actor: str, documents: DocumentRepository,
                  audit: AuditRepository) -> Document:
    """Fetch a document's metadata. A view is an access, so it is logged and audited."""
    doc = _get(document_id, documents)
    documents.log_access(document_id, actor, "view")
    audit.append(AuditEntry(id=None, job_id=None, deal_id=doc.deal_id, actor=actor,
                            action="document_viewed", created_at=utcnow(),
                            payload={"document_id": doc.id}))
    return doc


def list_versions(document_id: int, documents: DocumentRepository) -> list[DocumentVersion]:
    _get(document_id, documents)
    return documents.list_versions(document_id)


def update_document(document_id: int, is_executed: bool | None, doc_class: DocClass | None,
                    actor: str, actor_role: Role, documents: DocumentRepository,
                    audit: AuditRepository) -> Document:
    """Mark a document executed and/or set its class. A class set by a person is confirmed."""
    require(actor_role, Capability.EDIT_DEAL_DATA, "edit documents")
    doc = _get(document_id, documents)
    changes: dict = {}
    if doc_class is not None:
        doc = documents.update_classification(document_id, doc_class, True)
        changes["doc_class"] = doc_class.value
        changes["class_confirmed"] = True
    if is_executed is not None:
        doc = documents.set_executed(document_id, is_executed)
        changes["is_executed"] = is_executed
    audit.append(AuditEntry(id=None, job_id=None, deal_id=doc.deal_id, actor=actor,
                            action="document_updated", created_at=utcnow(),
                            payload={"document_id": doc.id, **changes}))
    return doc
