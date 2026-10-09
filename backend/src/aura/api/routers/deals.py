from fastapi import APIRouter, Depends, status

from aura.api.deps import (current_user, get_audit, get_deals, get_diligence, get_guards,
                           get_history, get_mandates, get_parties, get_signoffs, get_users,
                           get_walls)
from aura.api.errors import evaluation_out
from aura.api.deps import get_notes
from aura.api.schemas.harness import NoteOut
from aura.core.services.notes import list_notes
from aura.api.schemas.deals import (CreateDealRequest, CreateMandateRequest, DealDetailOut,
                                    DealOut, DealPartyOut, EvaluationOut, HistoryOut,
                                    LinkPartyRequest, MandateOut, MemberOut, MemberRequest,
                                    SignoffOut, SignoffRequest, TransitionOut,
                                    TransitionRequest, UpdateDealRequest)
from aura.core.domain.enums import DealStage
from aura.core.domain.errors import NotFound
from aura.core.domain.mandate import MandateCriterion
from aura.core.domain.user import User
from aura.core.policy.stage_policy import allowed_next
from aura.core.services import compliance
from aura.core.services import walls as wall_service
from aura.core.services.create_deal import create_deal
from aura.core.services.deal_profile import update_deal_profile
from aura.core.services.mandates import create_mandate
from aura.core.services.parties import link_party
from aura.core.services.transition_deal import preview_guards, transition_deal

router = APIRouter(prefix="/api/deals", tags=["deals"])


def deal_out(d) -> DealOut:
    return DealOut(id=d.id, external_id=d.external_id, name=d.name, stage=d.stage.value,
                   transaction_class=d.transaction_class.value, owner=d.owner,
                   outcome=d.outcome.value if d.outcome else None,
                   opened_at=d.opened_at, closed_at=d.closed_at,
                   regulatory_flags=list(d.regulatory_flags), profile=dict(d.profile),
                   profile_schema_version=d.profile_schema_version)


def _mandate_out(m) -> MandateOut:
    return MandateOut(id=m.id, deal_id=m.deal_id, title=m.title, notes=m.notes,
                      side=m.side.value, status=m.status.value, created_at=m.created_at,
                      criteria=[{"criterion_key": c.criterion_key, "operator": c.operator,
                                 "value": c.value, "hardness": c.hardness,
                                 "weight": c.weight} for c in m.criteria])


def _signoff_out(s) -> SignoffOut:
    return SignoffOut(id=s.id, deal_id=s.deal_id, signed_by=s.signed_by, note=s.note,
                      signed_at=s.signed_at)


def _deal_or_404(deal_id: int, deals):
    deal = deals.get(deal_id)
    if deal is None:
        raise NotFound("Deal not found")
    return deal


@router.get("", response_model=list[DealOut])
def list_deals(user: User = Depends(current_user), deals=Depends(get_deals)):
    return [deal_out(d) for d in deals.list_all()]


@router.post("", response_model=DealOut, status_code=status.HTTP_201_CREATED)
def create(body: CreateDealRequest, user: User = Depends(current_user),
           deals=Depends(get_deals), history=Depends(get_history), audit=Depends(get_audit),
           walls=Depends(get_walls), users=Depends(get_users)):
    deal = create_deal(body.external_id, body.name, body.transaction_class, user.username,
                       user.role, deals, history, audit, walls, users,
                       profile=body.profile, profile_schema_version=body.profile_schema_version)
    return deal_out(deal)


@router.get("/{deal_id}", response_model=DealDetailOut)
def get_deal(deal_id: int, user: User = Depends(current_user), deals=Depends(get_deals),
             parties=Depends(get_parties), history=Depends(get_history)):
    deal = _deal_or_404(deal_id, deals)
    return DealDetailOut(
        **deal_out(deal).model_dump(),
        parties=[DealPartyOut(party_id=p.party_id, display_name=p.display_name,
                              role=p.role.value) for p in parties.list_for_deal(deal_id)],
        history=[HistoryOut(from_stage=h.from_stage.value if h.from_stage else None,
                            to_stage=h.to_stage.value, entered_at=h.entered_at, actor=h.actor,
                            reason_code=h.reason_code, is_regression=h.is_regression)
                 for h in history.list_for_deal(deal_id)],
        allowed_next=[s.value for s in allowed_next(deal.stage)])


@router.patch("/{deal_id}", response_model=DealOut)
def update_deal(deal_id: int, body: UpdateDealRequest, user: User = Depends(current_user),
                deals=Depends(get_deals), audit=Depends(get_audit)):
    """Regulatory flags: dealmaker or compliance. Flags make T9 wait for a compliance
    sign-off. Profile (class-specific terms, whole object): dealmaker or analyst. When both
    are given, both must succeed or neither is saved."""
    deal = None
    if body.regulatory_flags is not None:
        deal = compliance.set_regulatory_flags(deal_id, body.regulatory_flags,
                                               user.username, user.role, deals, audit)
    if body.profile is not None:
        deal = update_deal_profile(deal_id, body.profile, user.username, user.role, deals,
                                   audit, body.profile_schema_version)
    return deal_out(deal)


@router.get("/{deal_id}/guards", response_model=list[EvaluationOut])
def guard_preview(deal_id: int, to_stage: DealStage, user: User = Depends(current_user),
                  deals=Depends(get_deals), guards=Depends(get_guards)):
    return [evaluation_out(e) for e in preview_guards(deal_id, to_stage, deals, guards)]


@router.post("/{deal_id}/transition", response_model=TransitionOut)
def transition(deal_id: int, body: TransitionRequest, user: User = Depends(current_user),
               deals=Depends(get_deals), history=Depends(get_history),
               guards=Depends(get_guards), diligence=Depends(get_diligence),
               audit=Depends(get_audit)):
    result = transition_deal(deal_id, body.to_stage, user.username, user.role,
                             body.reason_code, body.override_justification, deals, history,
                             guards, diligence, audit)
    return TransitionOut(deal=deal_out(result.deal),
                         evaluations=[evaluation_out(e) for e in result.evaluations])


@router.post("/{deal_id}/parties", response_model=DealPartyOut,
             status_code=status.HTTP_201_CREATED)
def add_party(deal_id: int, body: LinkPartyRequest, user: User = Depends(current_user),
              deals=Depends(get_deals), parties=Depends(get_parties),
              audit=Depends(get_audit)):
    link = link_party(deal_id, body.party_id, body.role, user.username, user.role, deals,
                      parties, audit)
    return DealPartyOut(party_id=link.party_id, display_name=link.display_name,
                        role=link.role.value)


@router.get("/{deal_id}/mandates", response_model=list[MandateOut])
def list_mandates(deal_id: int, user: User = Depends(current_user), deals=Depends(get_deals),
                  mandates=Depends(get_mandates)):
    _deal_or_404(deal_id, deals)
    return [_mandate_out(m) for m in mandates.list_for_deal(deal_id)]


@router.post("/{deal_id}/mandates", response_model=MandateOut,
             status_code=status.HTTP_201_CREATED)
def add_mandate(deal_id: int, body: CreateMandateRequest, user: User = Depends(current_user),
                deals=Depends(get_deals), mandates=Depends(get_mandates),
                audit=Depends(get_audit)):
    criteria = [MandateCriterion(c.criterion_key.strip(), c.operator, c.value, c.hardness,
                                 c.weight) for c in body.criteria]
    return _mandate_out(create_mandate(deal_id, body.title, body.notes, body.side,
                                       body.status, criteria, user.username, user.role,
                                       deals, mandates, audit))


@router.get("/{deal_id}/signoffs", response_model=list[SignoffOut])
def list_signoffs(deal_id: int, user: User = Depends(current_user), deals=Depends(get_deals),
                  signoffs=Depends(get_signoffs)):
    return [_signoff_out(s) for s in compliance.list_signoffs(deal_id, deals, signoffs)]


@router.post("/{deal_id}/signoffs", response_model=SignoffOut,
             status_code=status.HTTP_201_CREATED)
def add_signoff(deal_id: int, body: SignoffRequest, user: User = Depends(current_user),
                deals=Depends(get_deals), signoffs=Depends(get_signoffs),
                audit=Depends(get_audit)):
    return _signoff_out(compliance.add_signoff(deal_id, body.note, user.username, user.role,
                                               deals, signoffs, audit))


@router.get("/{deal_id}/notes", response_model=list[NoteOut])
def get_notes_for_deal(deal_id: int, user: User = Depends(current_user),
                       deals=Depends(get_deals), notes=Depends(get_notes)):
    """Internal notes on the deal (written by the add_internal_note MCP tool), oldest first.
    404 if you are not on the deal's wall."""
    return [NoteOut(**vars(n)) for n in list_notes(deal_id, deals, notes)]


def _members_out(members) -> list[MemberOut]:
    return [MemberOut(username=m.username, added_at=m.added_at) for m in members]


@router.get("/{deal_id}/members", response_model=list[MemberOut])
def list_members(deal_id: int, user: User = Depends(current_user), deals=Depends(get_deals),
                 walls=Depends(get_walls)):
    return _members_out(wall_service.list_members(deal_id, deals, walls))


@router.post("/{deal_id}/members", response_model=list[MemberOut],
             status_code=status.HTTP_201_CREATED)
def add_member(deal_id: int, body: MemberRequest, user: User = Depends(current_user),
               deals=Depends(get_deals), walls=Depends(get_walls), users=Depends(get_users),
               audit=Depends(get_audit)):
    """Compliance manages walls but is bound by them: it must already be on this wall."""
    wall_service.add_member(deal_id, body.username, user.username, user.role, deals, walls,
                            users, audit)
    return _members_out(walls.members(deal_id))


@router.delete("/{deal_id}/members", response_model=list[MemberOut])
def remove_member(deal_id: int, body: MemberRequest, user: User = Depends(current_user),
                  deals=Depends(get_deals), walls=Depends(get_walls), audit=Depends(get_audit)):
    wall_service.remove_member(deal_id, body.username, user.username, user.role, deals,
                               walls, audit)
    return _members_out(walls.members(deal_id))