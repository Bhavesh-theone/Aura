"""Evaluation, autonomy, prompt registry and traces (agentic-harness categories 9 and 10)."""
from fastapi import APIRouter, Depends

from aura.agents import prompts
from aura.api.deps import (current_user, get_audit, get_autonomy, get_evals, get_handoffs,
                           get_traces)
from aura.api.schemas.harness import (AutonomyOut, EvalCaseOut, EvalRunDetailOut, EvalRunOut,
                                      OverrideRateOut, PromptTemplateOut, TraceOut,
                                      TraceSpanOut)
from aura.config import get_settings
from aura.core.clock import utcnow
from aura.core.domain.errors import NotFound
from aura.core.domain.harness import EVAL_CAPABILITIES
from aura.core.domain.user import User
from aura.core.services.autonomy import promote
from aura.core.services.evaluation import override_rates

router = APIRouter(prefix="/api", tags=["harness"])


def _run_out(run) -> dict:
    return {k: getattr(run, k) for k in EvalRunOut.model_fields}


@router.get("/evals/runs", response_model=list[EvalRunOut])
def list_eval_runs(capability: str | None = None, limit: int = 50,
                   user: User = Depends(current_user), evals=Depends(get_evals)):
    """Golden-set eval runs, newest first (every signed-in role: eval data names no deal)."""
    return [EvalRunOut(**_run_out(r)) for r in evals.list_runs(capability, min(limit, 500))]


@router.get("/evals/runs/{run_id}", response_model=EvalRunDetailOut)
def get_eval_run(run_id: int, user: User = Depends(current_user), evals=Depends(get_evals)):
    run = evals.get_run(run_id)
    if run is None:
        raise NotFound("Eval run not found")
    return EvalRunDetailOut(**_run_out(run), cases=[
        EvalCaseOut(**{k: getattr(c, k) for k in EvalCaseOut.model_fields})
        for c in run.cases])


@router.get("/evals/override-rates", response_model=list[OverrideRateOut])
def get_override_rates(user: User = Depends(current_user), handoffs=Depends(get_handoffs)):
    """Per capability over the last 30 days of resolved handoffs on deals you can see."""
    rates = override_rates(handoffs.list_all(resolved=True), utcnow())
    return [OverrideRateOut(**vars(r)) for r in rates.values()]


@router.get("/autonomy", response_model=list[AutonomyOut])
def list_autonomy(user: User = Depends(current_user), autonomy=Depends(get_autonomy)):
    return [AutonomyOut(**vars(autonomy.get(c))) for c in EVAL_CAPABILITIES]


@router.post("/autonomy/{capability}/promote", response_model=AutonomyOut)
def promote_capability(capability: str, user: User = Depends(current_user),
                       autonomy=Depends(get_autonomy), evals=Depends(get_evals),
                       audit=Depends(get_audit)):
    """Admin only (403 otherwise). One level up, and only with a passing eval run from the
    last 7 days (409 otherwise). Audited 'autonomy_promoted'."""
    saved = promote(capability, user.username, user.role, autonomy, evals, audit,
                    include_stub_evals=get_settings().autonomy_counts_stub_evals)
    return AutonomyOut(**vars(saved))


@router.get("/prompts", response_model=list[PromptTemplateOut])
def list_prompts(user: User = Depends(current_user)):
    """The versioned prompt templates (read-only); `active` marks the version in use."""
    return [PromptTemplateOut(template_id=t.template_id, version=t.version, ref=t.ref,
                              role=t.role, sha256=t.sha256, path=t.path,
                              active=prompts.ACTIVE.get(t.template_id) == t.version)
            for t in prompts.all_templates()]


@router.get("/traces/{trace_id}", response_model=TraceOut)
def get_trace(trace_id: str, user: User = Depends(current_user), traces=Depends(get_traces)):
    """A trace's spans, oldest first. Spans on deals you are not on are left out; 404 when
    none is visible."""
    spans = traces.list_trace(trace_id)
    if not spans:
        raise NotFound("Trace not found")
    return TraceOut(trace_id=trace_id, spans=[TraceSpanOut(
        trace_id=s.trace_id, span_id=s.span_id, parent_span_id=s.parent_span_id, name=s.name,
        start=s.start, end=s.end, attributes=s.attributes, status=s.status,
        duration_ms=round((s.end - s.start).total_seconds() * 1000, 3) if s.end else None)
        for s in spans])
