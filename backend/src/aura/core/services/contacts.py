"""Party email contacts and the suppression (do-not-contact) list. Every change is audited.

An address is only ever used for outbound email once a dealmaker has verified it and it is
the party's primary contact (see aura.core.services.outbound)."""
from aura.core.clock import utcnow
from aura.core.domain.audit import AuditEntry
from aura.core.domain.enums import Role
from aura.core.domain.errors import NotFound, RuleViolation
from aura.core.domain.outbound import PartyContact, Suppression, SuppressionKind
from aura.core.policy.email_policy import normalise_domain, normalise_email
from aura.core.policy.rbac_policy import Capability, require
from aura.core.ports.repositories import (AuditRepository, ContactRepository,
                                          PartyRepository, SuppressionRepository)

MAX_NAME = 200
MAX_REASON = 500


def _audit(audit: AuditRepository, actor: str, action: str, payload: dict) -> None:
    audit.append(AuditEntry(id=None, job_id=None, deal_id=None, actor=actor, action=action,
                            created_at=utcnow(), payload=payload))


def list_contacts(party_id: int, actor_role: Role, parties: PartyRepository,
                  contacts: ContactRepository) -> list[PartyContact]:
    require(actor_role, Capability.VIEW_CONTACTS, "view party contacts")
    if parties.get(party_id) is None:
        raise NotFound("Party not found")
    return contacts.list_for_party(party_id)


def add_contact(party_id: int, name: str, email: str, is_primary: bool, actor: str,
                actor_role: Role, parties: PartyRepository, contacts: ContactRepository,
                audit: AuditRepository) -> PartyContact:
    """A new contact starts unverified. Making it primary demotes the party's other
    contacts. A party's first contact is primary whatever was asked."""
    require(actor_role, Capability.MANAGE_CONTACTS, "add party contacts")
    if parties.get(party_id) is None:
        raise NotFound("Party not found")
    clean = normalise_email(email)
    name = (name or "").strip()[:MAX_NAME]
    existing = contacts.list_for_party(party_id)
    primary = bool(is_primary) or not existing
    if primary:
        for other in existing:
            if other.is_primary:
                other.is_primary = False
                contacts.update(other)
    saved = contacts.add(PartyContact(id=None, party_id=party_id, name=name, email=clean,
                                      is_primary=primary, created_by=actor,
                                      created_at=utcnow()))
    _audit(audit, actor, "contact_added", {"party_id": party_id, "contact_id": saved.id,
                                           "email": clean, "is_primary": primary})
    return saved


def remove_contact(party_id: int, contact_id: int, actor: str, actor_role: Role,
                   contacts: ContactRepository, audit: AuditRepository) -> None:
    require(actor_role, Capability.MANAGE_CONTACTS, "remove party contacts")
    contact = contacts.get(contact_id)
    if contact is None or contact.party_id != party_id:
        raise NotFound("Contact not found")
    contacts.delete(contact_id)
    _audit(audit, actor, "contact_removed", {"party_id": party_id, "contact_id": contact_id,
                                             "email": contact.email})


def verify_contact(contact_id: int, actor: str, actor_role: Role,
                   contacts: ContactRepository, audit: AuditRepository) -> PartyContact:
    """A dealmaker vouches for the address. Verifying twice changes nothing."""
    require(actor_role, Capability.VERIFY_CONTACT, "verify party contacts")
    contact = contacts.get(contact_id)
    if contact is None:
        raise NotFound("Contact not found")
    if contact.verified_at is not None:
        return contact
    contact.verified_at, contact.verified_by = utcnow(), actor
    saved = contacts.update(contact)
    _audit(audit, actor, "contact_verified", {"party_id": contact.party_id,
                                              "contact_id": contact_id,
                                              "email": contact.email})
    return saved


def primary_verified_email(party_id: int | None, contacts: ContactRepository) -> str | None:
    if party_id is None:
        return None
    return next((c.email for c in contacts.list_for_party(party_id)
                 if c.is_primary and c.verified_at is not None), None)


def primary_contact(party_id: int | None, contacts: ContactRepository) -> PartyContact | None:
    if party_id is None:
        return None
    return next((c for c in contacts.list_for_party(party_id) if c.is_primary), None)


def list_suppressions(actor_role: Role,
                      suppressions: SuppressionRepository) -> list[Suppression]:
    require(actor_role, Capability.MANAGE_SUPPRESSION, "view the suppression list")
    return suppressions.list_all()


def add_suppression(kind: str, value: str, reason: str, actor: str, actor_role: Role,
                    suppressions: SuppressionRepository,
                    audit: AuditRepository) -> Suppression:
    require(actor_role, Capability.MANAGE_SUPPRESSION, "edit the suppression list")
    try:
        kind_ = SuppressionKind(kind)
    except ValueError:
        raise RuleViolation("kind must be 'email' or 'domain'") from None
    clean = normalise_email(value) if kind_ is SuppressionKind.EMAIL \
        else normalise_domain(value)
    saved = suppressions.add(Suppression(id=None, kind=kind_, value=clean,
                                         reason=(reason or "").strip()[:MAX_REASON],
                                         created_by=actor, created_at=utcnow()))
    _audit(audit, actor, "suppression_added", {"suppression_id": saved.id,
                                               "kind": kind_.value, "value": clean})
    return saved


def remove_suppression(suppression_id: int, actor: str, actor_role: Role,
                       suppressions: SuppressionRepository, audit: AuditRepository) -> None:
    require(actor_role, Capability.MANAGE_SUPPRESSION, "edit the suppression list")
    entry = suppressions.get(suppression_id)
    if entry is None:
        raise NotFound("Suppression entry not found")
    suppressions.delete(suppression_id)
    _audit(audit, actor, "suppression_removed", {"suppression_id": suppression_id,
                                                 "kind": entry.kind.value,
                                                 "value": entry.value})
