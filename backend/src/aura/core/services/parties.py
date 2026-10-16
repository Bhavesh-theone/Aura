


from aura.core.clock import utcnow
from aura.core.domain.audit import AuditEntry
from aura.core.domain.enums import PartyRole, PartyType, Role
from aura.core.domain.errors import Conflict, NotFound
from aura.core.domain.party import DealParty, Party, PartyIdentifier
from aura.core.policy.identifier_policy import normalise_identifier
from aura.core.policy.rbac_policy import Capability, require
from aura.core.ports.repositories import AuditRepository, DealRepository, PartyRepository


def create_party(party_type: PartyType, display_name: str,
                 identifiers: list[PartyIdentifier], actor: str, actor_role: Role,
                 parties: PartyRepository, audit: AuditRepository) -> Party:
    """Validate identifier formats (RuleViolation) and reject duplicates (Conflict)."""
    require(actor_role, Capability.EDIT_DEAL_DATA, "create parties")
    clean: list[PartyIdentifier] = []
    for ident in identifiers:
        value = normalise_identifier(ident.scheme, ident.value)
        key = (ident.scheme, value)
        if key in {(c.scheme, c.value) for c in clean} or \
                parties.find_by_identifier(ident.scheme.value, value) is not None:
            raise Conflict(f"{ident.scheme.value} {value} is already registered")
        clean.append(PartyIdentifier(ident.scheme, value))
    now = utcnow()
    party = parties.add(Party(id=None, party_type=party_type, display_name=display_name,
                              created_at=now, identifiers=clean))
    audit.append(AuditEntry(id=None, job_id=None, deal_id=None, actor=actor,
                            action="party_created", created_at=now,
                            payload={"party_id": party.id, "display_name": display_name,
                                     "identifiers": [{"scheme": i.scheme.value,
                                                      "value": i.value} for i in clean]}))
    return party


def link_party(deal_id: int, party_id: int, role: PartyRole, actor: str, actor_role: Role,
               deals: DealRepository, parties: PartyRepository,
               audit: AuditRepository) -> DealParty:
    require(actor_role, Capability.EDIT_DEAL_DATA, "link parties to deals")
    if deals.get(deal_id) is None:
        raise NotFound("Deal not found")
    party = parties.get(party_id)
    if party is None:
        raise NotFound("Party not found")
    if any(p.party_id == party_id and p.role is role for p in parties.list_for_deal(deal_id)):
        raise Conflict("Party already has this role on the deal")
    link = parties.link(DealParty(deal_id=deal_id, party_id=party_id, role=role,
                                  display_name=party.display_name))
    audit.append(AuditEntry(id=None, job_id=None, deal_id=deal_id, actor=actor,
                            action="party_linked", created_at=utcnow(),
                            payload={"party_id": party_id, "role": role.value}))
    return link
