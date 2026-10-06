from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from fastapi.responses import FileResponse

from aura.api.deps import current_user, get_audit, get_deals, get_documents, get_store
from aura.api.schemas.deals import (DocumentOut, DocumentVersionOut,
                                    UpdateDocumentRequest)
from aura.core.domain.enums import DocClass
from aura.core.domain.errors import NotFound
from aura.core.domain.user import User
from aura.core.services import documents as document_service

router = APIRouter(tags=["documents"])


def _out(d) -> DocumentOut:
    return DocumentOut(id=d.id, deal_id=d.deal_id, doc_class=d.doc_class.value,
                       filename=d.filename, sha256=d.sha256, byte_size=d.byte_size,
                       current_version=d.current_version, contains_upsi=d.contains_upsi,
                       sensitivity=d.sensitivity, is_executed=d.is_executed,
                       class_confirmed=d.class_confirmed, uploaded_by=d.uploaded_by,
                       uploaded_at=d.uploaded_at)


@router.get("/api/deals/{deal_id}/documents", response_model=list[DocumentOut])
def list_documents(deal_id: int, user: User = Depends(current_user), deals=Depends(get_deals),
                   documents=Depends(get_documents)):
    """Listing is not an access: only viewing or downloading one document is logged."""
    if deals.get(deal_id) is None:
        raise NotFound("Deal not found")
    return [_out(d) for d in documents.list_for_deal(deal_id)]


@router.post("/api/deals/{deal_id}/documents", response_model=DocumentOut,
             status_code=status.HTTP_201_CREATED)
def upload(deal_id: int, file: UploadFile = File(...), doc_class: DocClass = Form(...),
           contains_upsi: bool = Form(False), sensitivity: int = Form(2),
           user: User = Depends(current_user), deals=Depends(get_deals),
           documents=Depends(get_documents), store=Depends(get_store),
           audit=Depends(get_audit)):
    doc = document_service.upload_document(
        deal_id, file.filename or "unnamed", file.file.read(), doc_class, contains_upsi,
        sensitivity, user.username, user.role, deals, documents, store, audit)
    return _out(doc)


@router.get("/api/documents/{document_id}", response_model=DocumentOut)
def view(document_id: int, user: User = Depends(current_user),
         documents=Depends(get_documents), audit=Depends(get_audit)):
    """Document metadata. Logged as a 'view' in doc_access_log and in the audit trail."""
    return _out(document_service.view_document(document_id, user.username, documents, audit))


@router.get("/api/documents/{document_id}/versions", response_model=list[DocumentVersionOut])
def versions(document_id: int, user: User = Depends(current_user),
             documents=Depends(get_documents)):
    return [DocumentVersionOut(version=v.version, sha256=v.sha256, byte_size=v.byte_size,
                               uploaded_by=v.uploaded_by, uploaded_at=v.uploaded_at)
            for v in document_service.list_versions(document_id, documents)]


@router.patch("/api/documents/{document_id}", response_model=DocumentOut)
def patch(document_id: int, body: UpdateDocumentRequest, user: User = Depends(current_user),
          documents=Depends(get_documents), audit=Depends(get_audit)):
    """Mark executed and/or set the class (setting it confirms it). Audited."""
    return _out(document_service.update_document(document_id, body.is_executed,
                                                 body.doc_class, user.username, user.role,
                                                 documents, audit))


@router.get("/api/documents/{document_id}/download")
def download(document_id: int, user: User = Depends(current_user),
             documents=Depends(get_documents), store=Depends(get_store),
             audit=Depends(get_audit)):
    doc = document_service.open_document(document_id, user.username, documents, audit)
    return FileResponse(store.path(doc.sha256), filename=doc.filename)