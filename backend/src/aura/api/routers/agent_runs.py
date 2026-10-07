from fastapi import APIRouter, Depends

from aura.api.deps import current_user, get_agent_runs, get_deals
from aura.api.schemas.handoffs import AgentRunDetailOut, AgentRunOut
from aura.core.domain.errors import NotFound
from aura.core.domain.user import User

router = APIRouter(prefix="/api/agent-runs", tags=["agent-runs"])


def _out(r) -> AgentRunOut:
    return AgentRunOut(
        id=r.id, job_id=r.job_id, deal_id=r.deal_id, task_id=r.task_id, archetype=r.archetype,
        model_id=r.model_id, model_version=r.model_version,
        prompt_template_id=r.prompt_template_id, prompt_hash=r.prompt_hash,
        confidence=r.confidence, tokens_in=r.tokens_in, tokens_out=r.tokens_out,
        cost_inr=r.cost_inr, latency_ms=r.latency_ms, started_at=r.started_at,
        completed_at=r.completed_at, tool_calls=r.tool_calls, trace_id=r.trace_id,
        span_id=r.span_id)


@router.get("", response_model=list[AgentRunOut])
def list_runs(deal_id: int | None = None, user: User = Depends(current_user),
              deals=Depends(get_deals), runs=Depends(get_agent_runs)):
    if deal_id is not None and deals.get(deal_id) is None:
        raise NotFound("Deal not found")
    return [_out(r) for r in runs.list_for(deal_id)]


@router.get("/{run_id}", response_model=AgentRunDetailOut)
def get_run(run_id: int, user: User = Depends(current_user), runs=Depends(get_agent_runs)):
    run = runs.get(run_id)
    if run is None:
        raise NotFound("Agent run not found")
    return AgentRunDetailOut(**_out(run).model_dump(), input_digest=run.input_digest,
                             output=run.output)
