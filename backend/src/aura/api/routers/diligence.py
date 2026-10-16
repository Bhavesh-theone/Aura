from fastapi import APIRouter, Depends, status

from aura.api.deps import (current_user, get_audit, get_conditions, get_deals, get_diligence,
                           get_documents, get_findings)
from aura.api.schemas.deals import (ConditionOut, CreateConditionRequest, CreateFindingRequest,
                                    DiligenceItemOut, FindingOut, UpdateConditionRequest,
                                    UpdateDiligenceRequest)
from aura.core.domain.errors import NotFound
from aura.core.domain.user import User
from aura.core.services.diligence import (add_condition, add_finding, update_condition,
                                          update_diligence_item)

router = APIRouter(tags=["diligence"])


def _item_out(i) -> DiligenceItemOut:
    return DiligenceItemOut(id=i.id, deal_id=i.deal_id, template_id=i.template_id,
                            prompt=i.prompt, severity=i.severity.value, status=i.status.value,
                            evidence_doc_ids=i.evidence_doc_ids,
                            waiver_justification=i.waiver_justification)


def _cp_out(c) -> ConditionOut:
    return ConditionOut(id=c.id, deal_id=c.deal_id, description=c.description,
                        cp_type=c.cp_type, status=c.status.value,
                        waiver_justification=c.waiver_justification)


def _finding_out(f) -> FindingOut:
    return FindingOut(id=f.id, diligence_item_id=f.diligence_item_id, deal_id=f.deal_id,
                      finding_type=f.finding_type.value, description=f.description,
                      quantified_impact_inr=f.quantified_impact_inr,
                      affects_valuation=f.affects_valuation, raised_by=f.raised_by,
                      raised_at=f.raised_at)


def _require_deal(deal_id: int, deals) -> None:
    if deals.get(deal_id) is None:
        raise NotFound("Deal not found")


@router.get("/api/deals/{deal_id}/diligence", response_model=list[DiligenceItemOut])
def list_items(deal_id: int, user: User = Depends(current_user), deals=Depends(get_deals),
               diligence=Depends(get_diligence)):
    _require_deal(deal_id, deals)
    return [_item_out(i) for i in diligence.list_items(deal_id)]


@router.patch("/api/diligence/{item_id}", response_model=DiligenceItemOut)
def patch_item(item_id: int, body: UpdateDiligenceRequest, user: User = Depends(current_user),
               diligence=Depends(get_diligence), documents=Depends(get_documents),
               audit=Depends(get_audit)):
    item = update_diligence_item(item_id, body.status, body.evidence_doc_ids,
                                 body.waiver_justification, user.username, user.role,
                                 diligence, documents, audit)
    return _item_out(item)


@router.get("/api/deals/{deal_id}/conditions", response_model=list[ConditionOut])
def list_conditions(deal_id: int, user: User = Depends(current_user), deals=Depends(get_deals),
                    conditions=Depends(get_conditions)):
    _require_deal(deal_id, deals)
    return [_cp_out(c) for c in conditions.list_for_deal(deal_id)]


@router.post("/api/deals/{deal_id}/conditions", response_model=ConditionOut,
             status_code=status.HTTP_201_CREATED)
def create_condition(deal_id: int, body: CreateConditionRequest,
                     user: User = Depends(current_user), deals=Depends(get_deals),
                     conditions=Depends(get_conditions), audit=Depends(get_audit)):
    return _cp_out(add_condition(deal_id, body.description, body.cp_type, user.username,
                                 user.role, deals, conditions, audit))


@router.patch("/api/conditions/{cp_id}", response_model=ConditionOut)
def patch_condition(cp_id: int, body: UpdateConditionRequest,
                    user: User = Depends(current_user), conditions=Depends(get_conditions),
                    audit=Depends(get_audit)):
    return _cp_out(update_condition(cp_id, body.status, body.waiver_justification,
                                    user.username, user.role, conditions, audit))


@router.get("/api/deals/{deal_id}/findings", response_model=list[FindingOut])
def list_findings(deal_id: int, user: User = Depends(current_user), deals=Depends(get_deals),
                  findings=Depends(get_findings)):
    _require_deal(deal_id, deals)
    return [_finding_out(f) for f in findings.list_for_deal(deal_id)]


@router.post("/api/deals/{deal_id}/findings", response_model=FindingOut,
             status_code=status.HTTP_201_CREATED)
def create_finding(deal_id: int, body: CreateFindingRequest,
                   user: User = Depends(current_user), deals=Depends(get_deals),
                   diligence=Depends(get_diligence), findings=Depends(get_findings),
                   audit=Depends(get_audit)):
    return _finding_out(add_finding(
        deal_id, body.diligence_item_id, body.finding_type, body.description,
        body.quantified_impact_inr, body.affects_valuation, user.username, user.role, deals,
        diligence, findings, audit))