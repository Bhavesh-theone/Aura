


from aura.core.clock import utcnow
from aura.core.domain.audit import AuditEntry
from aura.core.domain.enums import (CriterionHardness, CriterionOperator, MandateSide,
                                    MandateStatus, Role)
from aura.core.domain.errors import NotFound, RuleViolation
from aura.core.domain.mandate import Mandate, MandateCriterion
from aura.core.policy.rbac_policy import Capability, require
from aura.core.ports.repositories import AuditRepository, DealRepository, MandateRepository

_Op = CriterionOperator


def _is_number(v: object) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def check_criterion(c: MandateCriterion) -> None:
    """SOSPE §6.2 shape rules; RuleViolation (422) names the broken one."""
    key = c.criterion_key.strip()
    if not key:
        raise RuleViolation("A criterion needs a criterion_key")
    if c.weight is not None and not (_is_number(c.weight) and 0 <= c.weight <= 1):
        raise RuleViolation(f"{key}: weight must be between 0 and 1")
    if c.hardness is CriterionHardness.SOFT and c.weight is None:
        raise RuleViolation(f"{key}: soft criteria require a weight")
    v = c.value
    if c.operator is _Op.BETWEEN:
        if not (isinstance(v, list) and len(v) == 2):
            raise RuleViolation(f"{key}: 'between' needs a list of exactly two values")
    elif c.operator in (_Op.IN, _Op.NOT_IN):
        if not (isinstance(v, list) and v):
            raise RuleViolation(f"{key}: '{c.operator.value}' needs a non-empty list")
    elif c.operator in (_Op.GTE, _Op.LTE):
        if not _is_number(v):
            raise RuleViolation(f"{key}: '{c.operator.value}' needs a number")
    elif not ((isinstance(v, str) and v.strip()) or _is_number(v)):
        raise RuleViolation(f"{key}: '{c.operator.value}' needs a string or number")


def create_mandate(deal_id: int, title: str, notes: str, side: MandateSide,
                   status: MandateStatus, criteria: list[MandateCriterion],
                   actor: str, actor_role: Role, deals: DealRepository,
                   mandates: MandateRepository, audit: AuditRepository) -> Mandate:
    require(actor_role, Capability.EDIT_DEAL_DATA, "create mandates")
    if deals.get(deal_id) is None:
        raise NotFound("Deal not found")
    for c in criteria:
        check_criterion(c)
    now = utcnow()
    mandate = mandates.add(Mandate(id=None, deal_id=deal_id, title=title, notes=notes,
                                   side=side, status=status, created_at=now,
                                   criteria=criteria))
    audit.append(AuditEntry(id=None, job_id=None, deal_id=deal_id, actor=actor,
                            action="mandate_created", created_at=now,
                            payload={"mandate_id": mandate.id, "title": title,
                                     "side": side.value, "criteria": len(criteria),
                                     "hard": sum(c.hardness is CriterionHardness.HARD
                                                 for c in criteria)}))
    return mandate
