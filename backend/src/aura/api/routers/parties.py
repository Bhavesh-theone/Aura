from fastapi import APIRouter, Depends, status

from aura.api.deps import current_user, get_audit, get_contacts, get_parties
from aura.api.schemas.deals import CreatePartyRequest, PartyOut
from aura.api.schemas.outbound import ContactOut, CreateContactRequest
from aura.core.domain.party import PartyIdentifier
from aura.core.domain.user import User
from aura.core.services.contacts import (add_contact, list_contacts, remove_contact,
                                         verify_contact)
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


# --- email contacts (outbound email, migration 0013) -----------------------------------------

def _contact_out(c) -> ContactOut:
    return ContactOut(id=c.id, party_id=c.party_id, name=c.name, email=c.email,
                      is_primary=c.is_primary, verified_at=c.verified_at,
                      verified_by=c.verified_by, created_by=c.created_by,
                      created_at=c.created_at)


@router.get("/{party_id}/contacts", response_model=list[ContactOut])
def list_party_contacts(party_id: int, user: User = Depends(current_user),
                        parties=Depends(get_parties), contacts=Depends(get_contacts)):
    return [_contact_out(c) for c in list_contacts(party_id, user.role, parties, contacts)]


@router.post("/{party_id}/contacts", response_model=ContactOut,
             status_code=status.HTTP_201_CREATED)
def add_party_contact(party_id: int, body: CreateContactRequest,
                      user: User = Depends(current_user), parties=Depends(get_parties),
                      contacts=Depends(get_contacts), audit=Depends(get_audit)):
    return _contact_out(add_contact(party_id, body.name, body.email, body.is_primary,
                                    user.username, user.role, parties, contacts, audit))


@router.delete("/{party_id}/contacts/{contact_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_party_contact(party_id: int, contact_id: int, user: User = Depends(current_user),
                         contacts=Depends(get_contacts), audit=Depends(get_audit)):
    remove_contact(party_id, contact_id, user.username, user.role, contacts, audit)


@router.post("/contacts/{contact_id}/verify", response_model=ContactOut)
def verify_party_contact(contact_id: int, user: User = Depends(current_user),
                         contacts=Depends(get_contacts), audit=Depends(get_audit)):
    return _contact_out(verify_contact(contact_id, user.username, user.role, contacts, audit))
