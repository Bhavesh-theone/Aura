"""Autonomy and demotion (SOSPE 9.6, adapted; harness category 10).

Each capability has a level: 2 = a confident result may complete without a handoff, 1 = every
result goes to a person, 0 = switched off (submitting it is a 409).

Demotion is automatic and one level at a time (apply_demotions, run by the worker sweep and by
`python -m aura.evals.autonomy --apply`): when the latest eval run for the capability failed
its threshold, or when people overrode it more than 20% of the time over at least 20 decisions
in the last 30 days. Only evidence newer than the last demotion counts, so one bad week drops
a capability one level, not to zero. Promotion is never automatic: an admin promotes, one
level, and only with a passing eval run from the last 7 days. Both are audited.
"""
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from aura.core.clock import utcnow
from aura.core.domain.audit import AuditEntry
from aura.core.domain.errors import CapabilityDisabled, Conflict, NotFound
from aura.core.domain.enums import Role
from aura.core.domain.harness import (EVAL_CAPABILITIES, LEVEL_AUTONOMOUS, LEVEL_DISABLED,
                                      CapabilityAutonomy)
from aura.core.policy.rbac_policy import Capability, require
from aura.core.ports.repositories import (AuditRepository, AutonomyRepository, EvalRepository,
                                          HandoffRepository)
from aura.core.services.evaluation import aware, override_rates

PROMOTION_EVAL_MAX_AGE = timedelta(days=7)


@dataclass(frozen=True)
class DemotionRules:
    max_override_rate: float = 0.20
    min_decisions: int = 20
    window_days: int = 30
    include_stub_evals: bool = False


def level_of(autonomy: AutonomyRepository | None, capability: str | None) -> int:
    if autonomy is None or not capability:
        return LEVEL_AUTONOMOUS
    return autonomy.get(capability).level


def ensure_enabled(autonomy: AutonomyRepository | None, capability: str | None) -> None:
    """Refuse work on a capability at level 0 (CapabilityDisabled, a 409)."""
    if autonomy is None or not capability:
        return
    state = autonomy.get(capability)
    if state.level <= LEVEL_DISABLED:
        raise CapabilityDisabled(f"{capability} is disabled (autonomy level 0): "
                                 f"{state.reason or 'demoted'}")


def _demote(state: CapabilityAutonomy, reason: str, evidence: dict,
            autonomy: AutonomyRepository, audit: AuditRepository, now: datetime) -> dict:
    new = replace(state, level=state.level - 1, demoted_at=now, reason=reason,
                  updated_by="system", updated_at=now)
    autonomy.save(new)
    change = {"capability": state.capability, "from_level": state.level,
              "to_level": new.level, "reason": reason, "evidence": evidence}
    audit.append(AuditEntry(id=None, job_id=None, deal_id=None, actor="system",
                            action="autonomy_demoted", payload=change, created_at=now))
    return change


def apply_demotions(autonomy: AutonomyRepository, evals: EvalRepository,
                    handoffs: HandoffRepository, audit: AuditRepository,
                    rules: DemotionRules = DemotionRules(),
                    now: datetime | None = None) -> list[dict]:
    """Demote each capability that its newest evidence says is not performing. `handoffs`
    must be unscoped (SYSTEM): the rate is over every deal."""
    now = aware(now or utcnow())
    states = {c: autonomy.get(c) for c in EVAL_CAPABILITIES}
    resolved = handoffs.list_all(resolved=True)
    rates = override_rates(resolved, now, timedelta(days=rules.window_days),
                           since={c: s.demoted_at for c, s in states.items()})
    changes = []
    for capability, state in states.items():
        if state.level <= LEVEL_DISABLED:
            continue
        since = aware(state.demoted_at)
        latest = evals.latest(capability, include_stub=rules.include_stub_evals)
        if latest is not None and not latest.passed \
                and (since is None or aware(latest.completed_at) > since):
            changes.append(_demote(
                state, f"eval run {latest.id} scored {latest.score:.2f}, below its threshold "
                       f"{latest.threshold:.2f}",
                {"eval_run_id": latest.id, "score": latest.score,
                 "threshold": latest.threshold}, autonomy, audit, now))
            continue
        rate = rates[capability]
        if rate.decisions >= rules.min_decisions and rate.rate is not None \
                and rate.rate > rules.max_override_rate:
            changes.append(_demote(
                state, f"people overrode {rate.overrides} of {rate.decisions} decisions "
                       f"({rate.rate:.0%}) in {rules.window_days} days, above "
                       f"{rules.max_override_rate:.0%}",
                {"decisions": rate.decisions, "overrides": rate.overrides,
                 "override_rate": rate.rate}, autonomy, audit, now))
    return changes


def promote(capability: str, actor: str, actor_role: Role, autonomy: AutonomyRepository,
            evals: EvalRepository, audit: AuditRepository, include_stub_evals: bool = False,
            now: datetime | None = None) -> CapabilityAutonomy:
    """An admin raises a capability one level. Needs a passing eval run from the last 7 days."""
    require(actor_role, Capability.MANAGE_AUTONOMY, "promote a capability")
    if capability not in EVAL_CAPABILITIES:
        raise NotFound(f"Unknown capability {capability!r}")
    now = aware(now or utcnow())
    state = autonomy.get(capability)
    if state.level >= LEVEL_AUTONOMOUS:
        raise Conflict(f"{capability} is already at the highest level ({state.level})")
    latest = evals.latest(capability, include_stub=include_stub_evals)
    if latest is None or not latest.passed \
            or aware(latest.completed_at) < now - PROMOTION_EVAL_MAX_AGE:
        raise Conflict(f"Promoting {capability} needs a passing eval run from the last 7 days"
                       + ("" if include_stub_evals else " on the real model (stub runs do not "
                                                         "count)"))
    new = replace(state, level=state.level + 1, reason=f"promoted by {actor} on eval run "
                  f"{latest.id}", updated_by=actor, updated_at=now)
    saved = autonomy.save(new)
    audit.append(AuditEntry(id=None, job_id=None, deal_id=None, actor=actor,
                            action="autonomy_promoted", created_at=now,
                            payload={"capability": capability, "from_level": state.level,
                                     "to_level": new.level, "eval_run_id": latest.id,
                                     "score": latest.score}))
    return saved
