from fastapi import APIRouter, Depends, HTTPException, status

from aura.api.deps import (get_approvals, get_audit, get_events, get_jobs,
                           get_segments, require_admin)
from aura.api.schemas.dto import ApprovalResponse
from aura.core.domain.user import User
from aura.core.services.decide_approval import decide_approval

router = APIRouter(prefix="/api/approvals", tags=["approvals"])


def _to_response(a) -> ApprovalResponse:
    return ApprovalResponse(id=a.id, segment_id=a.segment_id, category=a.category.value,
                            proposed_action=a.proposed_action, status=a.status.value)


@router.get("", response_model=list[ApprovalResponse])
def list_pending(user: User = Depends(require_admin), approvals=Depends(get_approvals)):
    return [_to_response(a) for a in approvals.list_pending()]


def _decide(approval_id: int, approved: bool, user, jobs, segments, approvals, audit, events):
    try:
        decision = decide_approval(approval_id, approved, user.id, user.username,
                                   jobs, segments, approvals, audit, events)
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc))
    return _to_response(decision)


@router.post("/{approval_id}/approve", response_model=ApprovalResponse)
def approve(approval_id: int, user: User = Depends(require_admin), jobs=Depends(get_jobs),
            segments=Depends(get_segments), approvals=Depends(get_approvals),
            audit=Depends(get_audit), events=Depends(get_events)):
    return _decide(approval_id, True, user, jobs, segments, approvals, audit, events)


@router.post("/{approval_id}/reject", response_model=ApprovalResponse)
def reject(approval_id: int, user: User = Depends(require_admin), jobs=Depends(get_jobs),
           segments=Depends(get_segments), approvals=Depends(get_approvals),
           audit=Depends(get_audit), events=Depends(get_events)):
    return _decide(approval_id, False, user, jobs, segments, approvals, audit, events)
