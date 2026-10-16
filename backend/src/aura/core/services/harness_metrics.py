"""Evaluation and security metrics for GET /api/metrics (harness categories 10 and 11).
Wall-filtered where the data has a deal: override rates and handoff counts come from the
viewer's handoff repository, injection counts from the viewer's audit trail. Eval runs and
autonomy levels are deal-less and the same for everyone."""
from dataclasses import dataclass
from datetime import datetime

from aura.core.clock import utcnow
from aura.core.domain.enums import HandoffTrigger
from aura.core.domain.harness import EVAL_CAPABILITIES
from aura.core.ports.repositories import (AuditRepository, AutonomyRepository, EvalRepository,
                                          HandoffRepository)
from aura.core.services.evaluation import override_rates


@dataclass
class EvaluationMetrics:
    latest_runs: list[dict]
    override_rate: list[dict]
    autonomy: list[dict]


@dataclass
class SecurityMetrics:
    injection_suspected: int
    untrusted_content_handoffs: int


def evaluation_metrics(evals: EvalRepository, autonomy: AutonomyRepository,
                       handoffs: HandoffRepository, now: datetime | None = None
                       ) -> EvaluationMetrics:
    latest = []
    for capability in EVAL_CAPABILITIES:
        run = evals.latest(capability, include_stub=True)
        if run is not None:
            latest.append({"capability": capability, "eval_run_id": run.id,
                           "orchestrator": run.orchestrator, "model_id": run.model_id,
                           "score": run.score, "threshold": run.threshold,
                           "passed": run.passed, "completed_at": run.completed_at})
    rates = override_rates(handoffs.list_all(resolved=True), now or utcnow())
    return EvaluationMetrics(
        latest_runs=latest,
        override_rate=[vars(r) for r in rates.values()],
        autonomy=[{"capability": c, "level": (s := autonomy.get(c)).level,
                   "reason": s.reason, "demoted_at": s.demoted_at}
                  for c in EVAL_CAPABILITIES])


def security_metrics(audit: AuditRepository, handoffs: HandoffRepository) -> SecurityMetrics:
    return SecurityMetrics(
        injection_suspected=audit.count_by_action("injection_suspected"),
        untrusted_content_handoffs=sum(1 for h in handoffs.list_all()
                                       if h.trigger is HandoffTrigger.UNTRUSTED_CONTENT))
