from dataclasses import dataclass



from aura.core.clock import utcnow
from aura.core.domain.audit import AuditEntry
from aura.core.domain.deal import Deal, StageHistoryEntry
from aura.core.domain.enums import DealStage, GuardSeverity, Role
from aura.core.domain.errors import GuardBlocked, NotFound
from aura.core.domain.guard import GuardEvaluation, StageGuard
from aura.core.policy.rbac_policy import Capability, can, check_transition_actor
from aura.core.policy.stage_policy import OUTCOME_FOR_STAGE, check_transition
from aura.core.ports.repositories import (AuditRepository, DealRepository,
                                          DiligenceRepository, GuardRepository,
                                          StageHistoryRepository)
from aura.core.services.diligence import instantiate_checklist


@dataclass
class TransitionResult:
    deal: Deal
    evaluations: list[GuardEvaluation]


def _evaluate(deal: Deal, to_stage: DealStage, actor: str,
              guards: GuardRepository) -> list[tuple[StageGuard, GuardEvaluation]]:
    now = utcnow()
    results = []
    for g in guards.list_active(deal.stage, to_stage, deal.transaction_class):
        passed, detail = guards.evaluate(g, deal.id)
        results.append((g, GuardEvaluation(
            id=None, deal_id=deal.id, guard_id=g.id, guard_name=g.guard_name,
            severity=g.severity, attempted_at=now, result=passed, detail=detail,
            actor=actor, description=g.description, override_role=g.override_role)))
    return results


def preview_guards(deal_id: int, to_stage: DealStage, deals: DealRepository,
                   guards: GuardRepository) -> list[GuardEvaluation]:
    """Dry run: evaluate the guards for a move and write nothing."""
    deal = deals.get(deal_id)
    if deal is None:
        raise NotFound("Deal not found")
    return [ev for _, ev in _evaluate(deal, to_stage, "", guards)]


def transition_deal(
    deal_id: int,
    to_stage: DealStage,
    actor: str,
    actor_role: Role,
    reason_code: str | None,
    override_justification: str | None,
    deals: DealRepository,
    history: StageHistoryRepository,
    guards: GuardRepository,
    diligence: DiligenceRepository,
    audit: AuditRepository,
) -> TransitionResult:
    # Roles that can neither move a deal nor override any guard are refused before any
    # lookup; compliance is decided once the guards are known.
    if not (can(actor_role, Capability.TRANSITION_DEAL)
            or can(actor_role, Capability.OVERRIDE_OWN_GUARDS)):
        check_transition_actor(actor_role, "", [])
    deal = deals.get(deal_id)
    if deal is None:
        raise NotFound("Deal not found")
    from_stage = deal.stage
    is_regression = check_transition(from_stage, to_stage, reason_code)

    justification = (override_justification or "").strip()
    pairs = _evaluate(deal, to_stage, actor, guards)
    check_transition_actor(actor_role, justification,
                           [g.override_role for g, ev in pairs
                            if not ev.result and ev.severity is GuardSeverity.BLOCKING])
    blocked = []
    for g, ev in pairs:
        if ev.result or ev.severity is not GuardSeverity.BLOCKING:
            continue
        if justification and g.override_role == actor_role.value:
            ev.overridden_by, ev.override_justification = actor, justification
        else:
            blocked.append(ev)
    evaluations = [guards.record(ev) for _, ev in pairs]

    now = utcnow()
    if blocked:
        audit.append(AuditEntry(id=None, job_id=None, deal_id=deal.id, actor=actor,
                                action="deal_transition_blocked", created_at=now,
                                payload={"from": from_stage.value, "to": to_stage.value,
                                         "failed": [e.guard_name for e in blocked]}))
        names = ", ".join(e.guard_name for e in blocked)
        raise GuardBlocked(f"Blocked by guard(s): {names}", evaluations)

    deal.stage = to_stage
    deal.outcome = OUTCOME_FOR_STAGE.get(to_stage)
    deal.closed_at = now if deal.outcome else None
    deals.update(deal)
    entry = history.append(StageHistoryEntry(id=None, deal_id=deal.id, from_stage=from_stage,
                                             to_stage=to_stage, entered_at=now, actor=actor,
                                             reason_code=reason_code,
                                             is_regression=is_regression))
    if evaluations:
        guards.attach_history([e.id for e in evaluations], entry.id)
    audit.append(AuditEntry(id=None, job_id=None, deal_id=deal.id, actor=actor,
                            action="deal_transition", created_at=now,
                            payload={"from": from_stage.value, "to": to_stage.value,
                                     "reason_code": reason_code,
                                     "overridden": [e.guard_name for e in evaluations
                                                    if e.overridden_by]}))
    if to_stage is DealStage.DILIGENCE:
        instantiate_checklist(deal, diligence)
    return TransitionResult(deal, evaluations)
