from fastapi import APIRouter, Depends, status

from aura.api.deps import current_user, get_audit, get_parties
from aura.api.schemas.deals import CreatePartyRequest, PartyOut
from aura.core.domain.party import PartyIdentifier
from aura.core.domain.user import User
from aura.core.services.parties import create_party

router = APIRouter(prefix="/api/parties", tags=["parties"])


def _out(p) -> PartyOut:
    return PartyOut(id=p.id, party_type=p.party_type.value, display_name=p.display_name,
                    identifiers=[{"scheme": i.scheme, "value": i.value} for i in p.identifiers])


@router.get("", response_model=list[PartyOut])
def list_parties(user: User = Depends(current_user), parties=Depends(get_parties)):
    return [_out(p) for p in parties.list_all()]


@router.post("", response_model=PartyOut, status_code=status.HTTP_201_CREATED)
def create(body: CreatePartyRequest, user: User = Depends(current_user),
           parties=Depends(get_parties), audit=Depends(get_audit)):
    idents = [PartyIdentifier(i.scheme, i.value) for i in body.identifiers]
    return _out(create_party(body.party_type, body.display_name, idents, user.username,
                             user.role, parties, audit))
