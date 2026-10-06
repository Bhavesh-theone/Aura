"""Success metrics (PRD section 11, SM1-SM6) and cycle time (F1.5, I6).

Everything is computed from the repositories it is given, so a wall-scoped viewer gets
numbers over the deals they can see. Stage dwell comes ONLY from deal_stage_history.

SM1 is defined over forward moves (one stage ahead). Regressions and exits carry a
reason code instead of guards, so they are not part of it.
"""
import math
import statistics
from dataclasses import dataclass
from datetime import datetime, timezone

from aura.core.domain.deal import StageHistoryEntry
from aura.core.domain.enums import DealStage
from aura.core.policy.lineage_policy import is_traceable
from aura.core.policy.stage_policy import FORWARD_ORDER
from aura.core.ports.repositories import (AgentRunRepository, AuditRepository, DealRepository,
                                          GuardRepository, StageHistoryRepository)


@dataclass
class StageDwell:
    stage: str
    n: int
    median_hours: float
    p90_hours: float


@dataclass
class Metrics:
    stage_dwell: list[StageDwell]
    guarded_forward_transitions_pct: float
    runs_traceable_pct: float
    audit_chain_ok: bool
    handoff_rejections_422: int
    outbound_executed: int
    deals_closed_end_to_end: int


def _naive_utc(value: datetime) -> datetime:
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _percentile(sorted_values: list[float], fraction: float) -> float:
    """Nearest-rank percentile."""
    rank = max(1, math.ceil(fraction * len(sorted_values)))
    return sorted_values[rank - 1]


def _is_forward(entry: StageHistoryEntry) -> bool:
    if entry.from_stage is None or entry.is_regression:
        return False
    if entry.from_stage not in FORWARD_ORDER or entry.to_stage not in FORWARD_ORDER:
        return False
    return FORWARD_ORDER.index(entry.to_stage) == FORWARD_ORDER.index(entry.from_stage) + 1


def _pct(part: int, whole: int) -> float:
    return 100.0 if whole == 0 else round(100.0 * part / whole, 1)


def stage_dwell(history: list[StageHistoryEntry]) -> list[StageDwell]:
    """Hours spent in each stage, over stays that have ended (a later row exists)."""
    by_deal: dict[int, list[StageHistoryEntry]] = {}
    for entry in history:
        by_deal.setdefault(entry.deal_id, []).append(entry)
    hours: dict[str, list[float]] = {}
    for rows in by_deal.values():
        rows.sort(key=lambda e: (_naive_utc(e.entered_at), e.id or 0))
        for current, following in zip(rows, rows[1:]):
            delta = _naive_utc(following.entered_at) - _naive_utc(current.entered_at)
            hours.setdefault(current.to_stage.value, []).append(delta.total_seconds() / 3600)
    order = [s.value for s in DealStage]
    return [StageDwell(stage=stage, n=len(values),
                       median_hours=round(statistics.median(values), 4),
                       p90_hours=round(_percentile(sorted(values), 0.9), 4))
            for stage in order if (values := hours.get(stage))]


def compute_metrics(deals: DealRepository, history: StageHistoryRepository,
                    guards: GuardRepository, runs: AgentRunRepository,
                    audit: AuditRepository, audit_chain_ok: bool) -> Metrics:
    rows = history.list_all()
    forward = [e for e in rows if _is_forward(e)]
    linked = guards.linked_history_ids([e.id for e in forward]) if forward else set()
    guarded = [e for e in forward if e.id in linked]

    all_runs = runs.list_for(None, limit=100_000)
    traceable = sum(1 for r in all_runs if is_traceable(r.input_digest, r.prompt_hash))

    guarded_by_deal: dict[int, set[DealStage]] = {}
    for e in guarded:
        guarded_by_deal.setdefault(e.deal_id, set()).add(e.to_stage)
    needed = set(FORWARD_ORDER[1:])
    closed_end_to_end = sum(
        1 for d in deals.list_all()
        if d.stage is DealStage.CLOSED and needed <= guarded_by_deal.get(d.id, set()))

    return Metrics(
        stage_dwell=stage_dwell(rows),
        guarded_forward_transitions_pct=_pct(len(guarded), len(forward)),
        runs_traceable_pct=_pct(traceable, len(all_runs)),
        audit_chain_ok=audit_chain_ok,
        handoff_rejections_422=audit.count_by_action("handoff_rejected"),
        outbound_executed=audit.count_by_action("outbound_executed"),
        deals_closed_end_to_end=closed_end_to_end)
