from dataclasses import dataclass, field

from aura.core.domain.audit import AuditEntry
from aura.core.domain.enums import DealStage
from aura.core.policy.stage_policy import EXIT_STAGES, TERMINAL_STAGES
from aura.core.ports.repositories import (AuditRepository, DealRepository, DiligenceRepository,
                                          HandoffRepository)

RECENT_ACTIVITY = 10


@dataclass
class DashboardSummary:
    open_deals: int
    deals_by_class: dict[str, int]
    deals_by_stage: dict[str, int]
    decisions_waiting: int
    blockers_open: int
    closed_deals: int = 0
    ended_deals: int = 0
    recent_activity: list[AuditEntry] = field(default_factory=list)


def dashboard_summary(deals: DealRepository, handoffs: HandoffRepository,
                      diligence: DiligenceRepository,
                      audit: AuditRepository) -> DashboardSummary:
    """Everything here comes from repositories scoped to the viewer, so it only counts
    deals behind walls the viewer is on. open_deals and deals_by_class cover open deals;
    deals_by_stage covers every deal, closed and ended included."""
    all_deals = deals.list_all()
    open_deals = [d for d in all_deals if d.stage not in TERMINAL_STAGES]
    by_class: dict[str, int] = {}
    by_stage: dict[str, int] = {}
    for d in open_deals:
        by_class[d.transaction_class.value] = by_class.get(d.transaction_class.value, 0) + 1
    for d in all_deals:
        by_stage[d.stage.value] = by_stage.get(d.stage.value, 0) + 1
    return DashboardSummary(
        open_deals=len(open_deals), deals_by_class=by_class, deals_by_stage=by_stage,
        decisions_waiting=handoffs.count_waiting(),
        blockers_open=diligence.count_open_blockers(),
        closed_deals=sum(1 for d in all_deals if d.stage is DealStage.CLOSED),
        ended_deals=sum(1 for d in all_deals if d.stage in EXIT_STAGES),
        recent_activity=audit.list_recent(RECENT_ACTIVITY))
