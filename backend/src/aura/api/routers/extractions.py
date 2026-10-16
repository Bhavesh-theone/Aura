from fastapi import APIRouter, Depends

from aura.api.deps import current_user, get_audit, get_deals, get_documents, get_extractions
from aura.api.schemas.deals import ExtractionOut
from aura.core.domain.user import User
from aura.core.services.extractions import list_extractions, verify_extraction

router = APIRouter(tags=["extractions"])


def _out(e) -> ExtractionOut:
    return ExtractionOut(id=e.id, document_id=e.document_id, schema_name=e.schema_name,
                         payload=e.payload, confidence=e.confidence,
                         feeds_valuation=e.feeds_valuation,
                         human_verified_by=e.human_verified_by,
                         human_verified_at=e.human_verified_at, created_at=e.created_at)


@router.get("/api/deals/{deal_id}/extractions", response_model=list[ExtractionOut])
def list_for_deal(deal_id: int, user: User = Depends(current_user), deals=Depends(get_deals),
                  extractions=Depends(get_extractions)):
    return [_out(e) for e in list_extractions(deal_id, deals, extractions)]


@router.post("/api/extractions/{extraction_id}/verify", response_model=ExtractionOut)
def verify(extraction_id: int, user: User = Depends(current_user),
           extractions=Depends(get_extractions), documents=Depends(get_documents),
           audit=Depends(get_audit)):
    return _out(verify_extraction(extraction_id, user.username, user.role, extractions,
                                  documents, audit))
