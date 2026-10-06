from typing import Literal

from fastapi import APIRouter, Body, Depends, Query, status

from aura.api.deps import (current_user, get_audit, get_deals, get_documents, get_events,
                           get_extractions, get_handoffs, get_jobs, get_segments, get_tasks)
from aura.api.schemas.handoffs import CreateHandoffRequest, HandoffOut
from aura.core.domain.errors import NotFound
from aura.core.domain.user import User
from aura.core.policy.rbac_policy import Capability, require
from aura.core.services.handoffs import create_handoff, resolve_handoff

router = APIRouter(prefix="/api/handoffs", tags=["handoffs"])


def handoff_out(h) -> HandoffOut:
    return HandoffOut(id=h.id, deal_id=h.deal_id, task_id=h.task_id, job_id=h.job_id,
                      task_type=h.task_type, direction=h.direction.value,
                      trigger=h.trigger.value, context_package=h.context_package,
                      directive=h.directive, status=h.status.value, created_at=h.created_at,
                      auto_escalate_at=h.auto_escalate_at, resolved_by=h.resolved_by,
                      resolved_at=h.resolved_at)


@router.get("", response_model=list[HandoffOut])
def list_handoffs(status_filter: Literal["open", "resolved"] | None = Query(None, alias="status"),
                  user: User = Depends(current_user), handoffs=Depends(get_handoffs)):
    """status=open also includes escalated handoffs: they still wait for a human."""
    resolved = None if status_filter is None else status_filter == "resolved"
    return [handoff_out(h) for h in handoffs.list_all(resolved)]


@router.post("", response_model=HandoffOut, status_code=status.HTTP_201_CREATED)
def create(body: CreateHandoffRequest, user: User = Depends(current_user),
           deals=Depends(get_deals), jobs=Depends(get_jobs), tasks=Depends(get_tasks),
           handoffs=Depends(get_handoffs), audit=Depends(get_audit),
           events=Depends(get_events)):
    require(user.role, Capability.EDIT_DEAL_DATA, "create handoffs")
    if body.job_id is not None and jobs.get(body.job_id) is None:
        raise NotFound("Job not found")
    handoff = create_handoff(
        deal_id=body.deal_id, job_id=body.job_id, task_type=body.task_type,
        assignment_mode=body.assignment_mode, direction=body.direction, trigger=body.trigger,
        context_package=body.context_package, directive=body.directive,
        materiality_inr=body.materiality_inr, actor=user.username, tasks=tasks,
        handoffs=handoffs, audit=audit, events=events, deals=deals)
    return handoff_out(handoff)


@router.get("/{handoff_id}", response_model=HandoffOut)
def get_handoff(handoff_id: int, user: User = Depends(current_user),
                handoffs=Depends(get_handoffs)):
    handoff = handoffs.get(handoff_id)
    if handoff is None:
        raise NotFound("Handoff not found")
    return handoff_out(handoff)


@router.post("/{handoff_id}/resolve", response_model=HandoffOut)
def resolve(handoff_id: int, body: dict = Body(...), user: User = Depends(current_user),
            jobs=Depends(get_jobs), segments=Depends(get_segments), tasks=Depends(get_tasks),
            handoffs=Depends(get_handoffs), documents=Depends(get_documents),
            audit=Depends(get_audit), events=Depends(get_events),
            extractions=Depends(get_extractions)):
    """The body is the directive itself: decision, reasoning, new_constraints,
    next_checkpoint. A {"directive": {...}} wrapper is accepted too."""
    directive = body["directive"] if isinstance(body.get("directive"), dict) else body
    handoff = resolve_handoff(handoff_id, directive, user.username, user.role, jobs, segments,
                              tasks, handoffs, documents, audit, events,
                              extractions=extractions)
    return handoff_out(handoff)
