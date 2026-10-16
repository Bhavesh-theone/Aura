from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from fastapi.responses import FileResponse

from aura.api.deps import (current_user, get_audit, get_deals, get_documents, get_session,
                           get_store)
from aura.api.schemas.deals import (ChunkOut, ChunkPageOut, DocumentFormatsOut, DocumentOut,
                                    DocumentVersionOut, SearchOut, UpdateDocumentRequest)
from aura.core.domain.enums import DocClass
from aura.core.domain.errors import NotFound
from aura.core.domain.user import User
from aura.core.services import documents as document_service
from aura.core.services import indexing
from aura.core.services.search import MAX_K, search
from aura.data.repositories.sql_ingest import SqlChunkRepository, SqlIndexQueue
from aura.ingest.parsers import check_upload, limits_from_settings, supported_extensions
from aura.ingest.wiring import query_embedder, search_params

router = APIRouter(tags=["documents"])


def _out(d) -> DocumentOut:
    return DocumentOut(id=d.id, deal_id=d.deal_id, doc_class=d.doc_class.value,
                       filename=d.filename, sha256=d.sha256, byte_size=d.byte_size,
                       current_version=d.current_version, contains_upsi=d.contains_upsi,
                       sensitivity=d.sensitivity, is_executed=d.is_executed,
                       class_confirmed=d.class_confirmed, uploaded_by=d.uploaded_by,
                       uploaded_at=d.uploaded_at, index_status=d.index_status,
                       indexed_at=d.indexed_at, chunk_count=d.chunk_count,
                       ocr_used=d.ocr_used, page_count=d.page_count,
                       warnings=list(d.index_warnings or []), index_error=d.index_error)


@router.get("/api/document-formats", response_model=DocumentFormatsOut)
def formats(user: User = Depends(current_user)):
    """What the upload accepts: extensions, the size limit and whether scans are OCR'd."""
    limits = limits_from_settings()
    exts = supported_extensions()
    return DocumentFormatsOut(extensions=exts, accept=",".join(exts),
                              max_upload_mb=limits.max_upload_mb,
                              ocr_enabled=limits.ocr_enabled)


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
           audit=Depends(get_audit), session=Depends(get_session)):
    """Upload (or add a version). 415 for a type Aura cannot read, 413 over max_upload_mb.
    The current version is queued for indexing (index_status 'pending')."""
    filename = file.filename or "unnamed"
    content = file.file.read(limits_from_settings().max_bytes + 1)
    check_upload(filename, content)
    doc = document_service.upload_document(
        deal_id, filename, content, doc_class, contains_upsi,
        sensitivity, user.username, user.role, deals, documents, store, audit,
        index_queue=SqlIndexQueue(session, user.username), index_state=documents)
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


@router.get("/api/documents/{document_id}/chunks", response_model=ChunkPageOut)
def chunks(document_id: int, offset: int = Query(0, ge=0),
           limit: int = Query(50, ge=1, le=200), user: User = Depends(current_user),
           documents=Depends(get_documents), session=Depends(get_session)):
    """The indexed chunks of the document's current version, in order (walled)."""
    doc = documents.get(document_id)
    if doc is None:
        raise NotFound("Document not found")
    total, items = SqlChunkRepository(session, user.username).list_for_document(
        document_id, offset, limit)
    return ChunkPageOut(document_id=doc.id, version=doc.current_version, total=total, items=[
        ChunkOut(chunk_index=c.chunk_index, kind=c.kind, page_from=c.page_from,
                 page_to=c.page_to, text=c.text, embedding_model=c.embedding_model,
                 risk_score=float(c.meta.get("risk_score", 0.0)),
                 matched_rules=list(c.meta.get("matched_rules", []))) for c in items])


@router.post("/api/documents/{document_id}/reindex", response_model=DocumentOut,
             status_code=status.HTTP_202_ACCEPTED)
def reindex(document_id: int, user: User = Depends(current_user),
            documents=Depends(get_documents), audit=Depends(get_audit),
            session=Depends(get_session)):
    """Queue the document for indexing again (dealmaker, analyst). Audited."""
    return _out(indexing.request_reindex(document_id, user.username, user.role, documents,
                                         SqlIndexQueue(session, user.username), documents,
                                         audit))


@router.get("/api/deals/{deal_id}/search", response_model=SearchOut)
def search_deal(deal_id: int, q: str = Query(..., min_length=1, max_length=500),
                k: int = Query(8, ge=1, le=MAX_K), user: User = Depends(current_user),
                deals=Depends(get_deals), session=Depends(get_session)):
    """Hybrid search (vector + full text, fused by RRF) over the deal's indexed chunks, as
    the caller: row-level security applies, and a deal off the caller's wall is a 404."""
    if deals.get(deal_id) is None:
        raise NotFound("Deal not found")
    response = search(deal_id, q, SqlChunkRepository(session, user.username),
                      query_embedder(), search_params(k))
    return SearchOut(query=response.query, k=response.k, mode=response.mode,
                     embedding_model=response.embedding_model, took_ms=response.took_ms,
                     warnings=response.warnings,
                     results=[dict(r.__dict__) for r in response.results])


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
