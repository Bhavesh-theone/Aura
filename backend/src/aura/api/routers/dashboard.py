from fastapi import APIRouter, Depends

from aura.api.deps import current_user, get_deals, get_diligence, get_handoffs, get_plain_audit
from aura.api.routers.activity import audit_out
from aura.api.schemas.handoffs import DashboardOut
from aura.core.domain.user import User
from aura.core.services.dashboard import dashboard_summary

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=DashboardOut)
def summary(user: User = Depends(current_user), deals=Depends(get_deals),
            handoffs=Depends(get_handoffs), diligence=Depends(get_diligence),
            audit=Depends(get_plain_audit)):
    s = dashboard_summary(deals, handoffs, diligence, audit)
    return DashboardOut(
        open_deals=s.open_deals, deals_by_class=s.deals_by_class,
        deals_by_stage=s.deals_by_stage, decisions_waiting=s.decisions_waiting,
        blockers_open=s.blockers_open, closed_deals=s.closed_deals,
        ended_deals=s.ended_deals,
        recent_activity=[audit_out(e) for e in s.recent_activity])
