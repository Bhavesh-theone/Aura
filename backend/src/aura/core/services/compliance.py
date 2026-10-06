"""Regulatory flags and compliance sign-off (PRD R3.8)."""



from aura.core.clock import utcnow
from aura.core.domain.audit import AuditEntry
from aura.core.domain.deal import Deal, DealSignoff
from aura.core.domain.enums import Role
from aura.core.domain.errors import NotFound, RuleViolation
from aura.core.policy.rbac_policy import Capability, require
from aura.core.ports.repositories import AuditRepository, DealRepository, SignoffRepository


def clean_flags(flags: list[str]) -> list[str]:
    """Trim, drop blanks, keep first occurrences in order."""
    if not isinstance(flags, list) or not all(isinstance(f, str) for f in flags):
        raise RuleViolation("regulatory_flags must be a list of strings")
    seen: list[str] = []
    for flag in (f.strip() for f in flags):
        if flag and flag not in seen:
            seen.append(flag)
    return seen


def set_regulatory_flags(deal_id: int, flags: list[str], actor: str, actor_role: Role,
                         deals: DealRepository, audit: AuditRepository) -> Deal:
    require(actor_role, Capability.EDIT_REGULATORY_FLAGS, "edit a deal's regulatory flags")
    deal = deals.get(deal_id)
    if deal is None:
        raise NotFound("Deal not found")
    before = list(deal.regulatory_flags)
    deal.regulatory_flags = clean_flags(flags)
    saved = deals.update(deal)
    audit.append(AuditEntry(id=None, job_id=None, deal_id=deal_id, actor=actor,
                            action="deal_flags_updated", created_at=utcnow(),
                            payload={"from": before, "to": saved.regulatory_flags}))
    return saved


def add_signoff(deal_id: int, note: str, actor: str, actor_role: Role,
                deals: DealRepository, signoffs: SignoffRepository,
                audit: AuditRepository) -> DealSignoff:
    require(actor_role, Capability.SIGN_OFF, "sign a deal off")
    if deals.get(deal_id) is None:
        raise NotFound("Deal not found")
    now = utcnow()
    signoff = signoffs.add(DealSignoff(id=None, deal_id=deal_id, signed_by=actor,
                                       note=note, signed_at=now))
    audit.append(AuditEntry(id=None, job_id=None, deal_id=deal_id, actor=actor,
                            action="deal_signoff", created_at=now,
                            payload={"signoff_id": signoff.id, "note": note}))
    return signoff


def list_signoffs(deal_id: int, deals: DealRepository,
                  signoffs: SignoffRepository) -> list[DealSignoff]:
    if deals.get(deal_id) is None:
        raise NotFound("Deal not found")
    return signoffs.list_for_deal(deal_id)
