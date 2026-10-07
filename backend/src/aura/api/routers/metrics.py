from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from aura.api.deps import (current_user, get_agent_runs, get_anchor_path, get_deals,
                           get_guards, get_history, get_plain_audit, get_session)
from aura.api.schemas.deals import (MetricsOut, ReliabilityMetricsOut, StageDwellOut,
                                    SuccessMetricsOut)
from aura.core.domain.user import User
from aura.core.services.metrics import compute_metrics
from aura.data.verify_audit import verify

router = APIRouter(prefix="/api/metrics", tags=["metrics"])


@router.get("", response_model=MetricsOut)
def metrics(user: User = Depends(current_user), s: Session = Depends(get_session),
            deals=Depends(get_deals), history=Depends(get_history),
            guards=Depends(get_guards), runs=Depends(get_agent_runs),
            audit=Depends(get_plain_audit),
            anchor_path: Path | None = Depends(get_anchor_path)):
    """Wall-filtered. Stage dwell comes only from deal_stage_history (completed stays).
    guarded_forward_transitions_pct (SM1) is defined over forward moves: regressions and
    exits carry a reason code rather than guards."""
    m = compute_metrics(deals, history, guards, runs, audit,
                        audit_chain_ok=verify(s, anchor_path).ok)
    return MetricsOut(
        stage_dwell=[StageDwellOut(stage=d.stage, n=d.n, median_hours=d.median_hours,
                                   p90_hours=d.p90_hours) for d in m.stage_dwell],
        success=SuccessMetricsOut(
            guarded_forward_transitions_pct=m.guarded_forward_transitions_pct,
            runs_traceable_pct=m.runs_traceable_pct, audit_chain_ok=m.audit_chain_ok,
            handoff_rejections_422=m.handoff_rejections_422,
            outbound_executed=m.outbound_executed,
            deals_closed_end_to_end=m.deals_closed_end_to_end),
        reliability=ReliabilityMetricsOut(**vars(m.reliability)) if m.reliability else None)

