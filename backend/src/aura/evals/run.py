"""Run a capability against its golden set, through the real orchestrator path.

    uv run python -m aura.evals.run --capability classify_document|extract_financials|
        draft_email|all [--orchestrator stub|crew] [--limit N]

Each golden case becomes the same context a job would get (screened and wrapped by
context_assembly), goes through Orchestrator.run, and is scored deterministically
(aura.core.services.evaluation). Every model call is recorded in agent_run with an 'eval:'
archetype and no deal or job, so lineage stays complete. The run is stored as an eval_run row
with one eval_case_result per case, a summary table is printed, and the exit code is 1 when a
capability scores below its threshold (AURA_EVAL_THRESHOLD_<CAPABILITY>), 2 on a setup error.

The stub orchestrator is deterministic and fast (for tests and CI); the crew needs Ollama.
"""
import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

from sqlalchemy import inspect
from sqlalchemy.orm import Session

from aura.config import BACKEND_DIR, get_settings
from aura.core.clock import utcnow
from aura.core.domain.harness import EVAL_CAPABILITIES, EvalCaseResult, EvalRun
from aura.core.ports.orchestrator import RunContext
from aura.core.services.context_assembly import ContextLimits, compose
from aura.core.services.evaluation import (FIGURES, classification_metrics, draft_metrics,
                                           extraction_metrics, score_draft, score_extraction)
from aura.core.tracing import tracer

GOLDEN_DIR = BACKEND_DIR / "evals" / "golden"
EVAL_DEAL = {"id": None, "external_id": "EVAL", "name": "Golden-set evaluation",
             "stage": "DILIGENCE"}
PRIMARY = {"classify_document": "accuracy", "extract_financials": "case_accuracy",
           "draft_email": "rubric_pass_rate"}


def golden_path(capability: str) -> Path:
    return GOLDEN_DIR / f"{capability}.jsonl"


def load_golden(capability: str, limit: int | None = None) -> tuple[list[dict], str]:
    """(cases, sha256 of the file with LF line endings): the version that was scored."""
    text = golden_path(capability).read_text(encoding="utf-8").replace("\r\n", "\n")
    cases = [json.loads(line) for line in text.splitlines() if line.strip()]
    return (cases[:limit] if limit else cases), hashlib.sha256(text.encode()).hexdigest()


def threshold_for(capability: str) -> float:
    return float(getattr(get_settings(), f"eval_threshold_{capability}"))


class CapturingSink:
    """Passes runs to the real sink and remembers the ids of the current case's runs."""

    def __init__(self, inner):
        self.inner, self.ids = inner, []

    def record(self, run):
        saved = self.inner.record(run)
        self.ids.append(saved.id)
        return saved


def case_context(capability: str, case: dict, limits: ContextLimits) -> dict:
    """The context a job for this case would carry, built by the same assembly code."""
    if capability == "draft_email":
        party = {"id": None, **(case.get("party") or {})}
        return compose({"capability": capability, "deal": {**EVAL_DEAL, **case["deal"]},
                        "party": party, "brief": case.get("brief", "")}, None, [], limits)
    document = {"id": None, "filename": case["filename"],
                "current_class": case.get("current_class") or "financial_statement",
                "excerpt": "", "version": 1}
    return compose({"capability": capability, "deal": dict(EVAL_DEAL), "document": document},
                   case.get("excerpt") or "", [], limits)


def run_case(orchestrator, capability: str, case: dict, sink: CapturingSink,
             limits: ContextLimits) -> tuple[EvalCaseResult, dict]:
    """Score one case. Returns the stored result and the row used for the aggregate."""
    context = case_context(capability, case, limits)
    sink.ids = []
    screening = context.get("screening") or {}
    run_context = RunContext(job_id=None, deal_id=None, task_id=None, runs=sink,
                             username=None, archetype_prefix="eval:",
                             notes={"eval_case": case["id"],
                                    "screening": {k: screening.get(k) for k in
                                                  ("risk_score", "matched_rules")}})
    clock = time.perf_counter()
    error, result = None, None
    with tracer.span("eval.case", {"aura.eval.case_id": case["id"],
                                   "aura.capability": capability}):
        try:
            result = orchestrator.run(context, run_context)
        except Exception as exc:  # a case that crashes is a failed case, not a failed run
            error = f"{type(exc).__name__}: {exc}"
    latency = int((time.perf_counter() - clock) * 1000)
    run_id = sink.ids[-1] if sink.ids else None
    action = result.proposed_action if result else None
    args = action.arguments if action else {}

    if capability == "classify_document":
        predicted = args.get("proposed_class")
        confidence = args.get("confidence")
        passed = predicted == case["expected_class"]
        row = (case["expected_class"], predicted or "(none)", confidence)
        return EvalCaseResult(
            id=None, eval_run_id=None, case_id=case["id"], passed=passed,
            score=1.0 if passed else 0.0, confidence=confidence,
            expected={"doc_class": case["expected_class"]},
            actual={"doc_class": predicted, "rationale": args.get("rationale")},
            agent_run_id=run_id, latency_ms=latency, error=error), row

    if capability == "extract_financials":
        extraction = result.extraction if result else None
        actual = dict(extraction.payload) if extraction else {k: None for k in FIGURES}
        confidence = extraction.confidence if extraction else None
        scored = score_extraction(case["expected"], actual,
                                  case.get("tolerance") or {"rel": 0.01, "abs": 1})
        return EvalCaseResult(
            id=None, eval_run_id=None, case_id=case["id"], passed=scored["passed"],
            score=scored["score"], confidence=confidence, expected=case["expected"],
            actual=actual, detail={"fields": scored["fields"]}, agent_run_id=run_id,
            latency_ms=latency, error=error), {**scored, "confidence": confidence}

    subject, body = args.get("subject") or "", args.get("body") or ""
    scored = score_draft(subject, body, case)
    if error:
        scored = {**scored, "passed": False, "score": 0.0}
    return EvalCaseResult(
        id=None, eval_run_id=None, case_id=case["id"], passed=scored["passed"],
        score=scored["score"], confidence=None, expected={"rules": list(scored["rules"])},
        actual={"subject": subject, "body": body},
        detail={"rules": scored["rules"], "words": scored["words"],
                "invented_amounts": scored["invented_amounts"]},
        agent_run_id=run_id, latency_ms=latency, error=error), {**scored, "confidence": None}


def evaluate(capability: str, orchestrator, orchestrator_name: str, model_id: str,
             session: Session, limit: int | None = None,
             threshold: float | None = None, created_by: str = "cli") -> EvalRun:
    """Run, score and store one capability's golden set. Commits."""
    from aura.data.repositories.sql_harness import SqlEvalRepository
    from aura.data.run_sink import SqlAgentRunSink
    from aura.data.spans import flush_spans

    s = get_settings()
    limits = ContextLimits(max_chars=s.max_context_chars, excerpt_chars=s.context_excerpt_chars,
                           retrieval_top_k=0, injection_threshold=s.injection_risk_threshold)
    cases, digest = load_golden(capability, limit)
    threshold = threshold_for(capability) if threshold is None else threshold
    sink = CapturingSink(SqlAgentRunSink(session))
    started = utcnow()
    results, rows = [], []
    with tracer.span("eval.run", {"aura.capability": capability,
                                  "aura.orchestrator": orchestrator_name,
                                  "gen_ai.request.model": model_id}) as span:
        for case in cases:
            result, row = run_case(orchestrator, capability, case, sink, limits)
            results.append(result)
            rows.append(row)
        if capability == "classify_document":
            metrics = classification_metrics(rows)
        elif capability == "extract_financials":
            metrics = extraction_metrics(rows)
        else:
            metrics = draft_metrics(rows)
        score = float(metrics[PRIMARY[capability]])
        metrics.update({"primary": PRIMARY[capability], "errors": sum(1 for r in results
                                                                      if r.error),
                        "total_latency_ms": sum(r.latency_ms for r in results),
                        "trace_id": span.trace_id})
        span.set("aura.eval.score", score)
    run = EvalRun(id=None, capability=capability, orchestrator=orchestrator_name,
                  model_id=model_id, golden_sha256=digest, n_cases=len(results), score=score,
                  threshold=threshold, passed=score >= threshold, metrics=metrics,
                  started_at=started, completed_at=utcnow(), created_by=created_by,
                  cases=results)
    saved = SqlEvalRepository(session).add_run(run)
    session.commit()
    flush_spans(session)
    return saved


def make_orchestrator(name: str):
    """(orchestrator, model_id). The crew needs Ollama; there is no silent stub fallback."""
    if name == "stub":
        from aura.worker.stub_orchestrator import StubOrchestrator
        return StubOrchestrator(), "stub"
    from aura.agents.llm.ollama_check import ollama_available
    s = get_settings()
    if not ollama_available(s.ollama_base_url):
        raise SystemExit(f"Ollama is not reachable at {s.ollama_base_url}: start it, or use "
                         "--orchestrator stub")
    from aura.agents.crewai.orchestrator import CrewOrchestrator
    return CrewOrchestrator(), s.ollama_model


def _fmt(value, pct: bool = False) -> str:
    if value is None:
        return "-"
    return f"{value:.0%}" if pct else f"{value:.2f}"


def summary_table(runs: list[EvalRun]) -> str:
    lines = [f"{'capability':<20} {'orch':<5} {'model':<14} {'n':>3} {'score':>6} "
             f"{'thresh':>6} {'pass':>5} {'macroF1':>7} {'meanconf':>8} {'cal>=.95':>10} "
             f"{'time':>8}  run"]
    for r in runs:
        m = r.metrics
        cal = m.get("calibration") or {}
        cal_text = f"{_fmt(cal.get('accuracy'), True)}({cal.get('n', 0)})"
        lines.append(
            f"{r.capability:<20} {r.orchestrator:<5} {r.model_id[:14]:<14} {r.n_cases:>3} "
            f"{_fmt(r.score):>6} {_fmt(r.threshold):>6} {'yes' if r.passed else 'NO':>5} "
            f"{_fmt(m.get('macro_f1')):>7} {_fmt(m.get('mean_confidence')):>8} "
            f"{cal_text:>10} {m.get('total_latency_ms', 0) / 1000:>7.1f}s  #{r.id}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m aura.evals.run",
                                     description="Score capabilities against golden sets.")
    parser.add_argument("--capability", required=True,
                        choices=[*EVAL_CAPABILITIES, "all"])
    parser.add_argument("--orchestrator", choices=["stub", "crew"], default="stub")
    parser.add_argument("--limit", type=int, default=None, help="cases per capability")
    args = parser.parse_args(argv)

    from aura.data.engine import SessionLocal, engine
    if not inspect(engine).has_table("eval_run"):
        print("The database has no eval tables yet: run `uv run alembic upgrade head` (or "
              "start the API once).", file=sys.stderr)
        return 2
    tracer.configure(get_settings().tracing_enabled)
    orchestrator, model_id = make_orchestrator(args.orchestrator)
    capabilities = list(EVAL_CAPABILITIES) if args.capability == "all" else [args.capability]
    runs = []
    with SessionLocal() as session:
        for capability in capabilities:
            runs.append(evaluate(capability, orchestrator, args.orchestrator, model_id,
                                 session, args.limit))
    print(summary_table(runs))
    failed = [r.capability for r in runs if not r.passed]
    if failed:
        print(f"BELOW THRESHOLD: {', '.join(failed)}")
        return 1
    print("All capabilities at or above their thresholds.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
