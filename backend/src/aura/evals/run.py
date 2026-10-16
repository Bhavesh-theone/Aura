"""Run a capability against its golden set, through the real orchestrator path.

    uv run python -m aura.evals.run --capability classify_document|extract_financials|
        draft_email|all [--orchestrator stub|crew] [--limit N] [--cases ID,ID]
    uv run python -m aura.evals.run --capability retrieval [--embedder ollama|fake]
        [--scan-vlm off|fallback|always]
    uv run python -m aura.evals.run --capability parsing [--pdf-parser pymupdf|docling|both]
        [--scan-vlm off|fallback|always]
    uv run python -m aura.evals.run --capability intake [--llm auto|ollama|off]

'retrieval' scores the hybrid search (aura.evals.retrieval): recall@5 and MRR over
evals/golden/retrieval.jsonl on the fixture deal pack, with the real Ollama embedder when it
answers (--embedder fake: deterministic hash vectors), over the Nilgiri and Kaveri fixture packs
parsed by the configured parser (scan VLM off unless --scan-vlm is given). 'parsing'
(aura.evals.parsing) scores the PDF parsers on the Kaveri fixtures against their ground truth
(default: both parsers when Docling is installed, scan VLM off). Neither is an agent
capability: they never touch autonomy.

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
from dataclasses import replace
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


def load_golden(capability: str, limit: int | None = None,
                case_ids: set[str] | None = None) -> tuple[list[dict], str]:
    """(cases, sha256 of the file with LF line endings): the version that was scored.
    `case_ids` keeps only those cases (before `limit`); the digest is still the whole file's."""
    text = golden_path(capability).read_text(encoding="utf-8").replace("\r\n", "\n")
    cases = [json.loads(line) for line in text.splitlines() if line.strip()]
    if case_ids:
        cases = [c for c in cases if c.get("id") in case_ids]
    return (cases[:limit] if limit else cases), hashlib.sha256(text.encode()).hexdigest()


def run_retrieval(args) -> int:
    from aura.data.engine import SessionLocal
    from aura.evals.retrieval import ALL_PACKS, evaluate_retrieval
    from aura.ingest.embedder import FakeEmbedder, OllamaEmbedder, embedder_available
    s = get_settings()
    if args.embedder == "fake":
        embedder = FakeEmbedder()
    else:
        embedder = OllamaEmbedder(s.ollama_base_url, s.embed_model, s.embed_batch,
                                  s.embed_timeout_seconds, s.embed_max_retries)
        if not embedder_available(embedder):
            if args.embedder == "ollama":
                print(f"{s.embed_model} is not available at {s.ollama_base_url}",
                      file=sys.stderr)
                return 2
            print(f"Ollama/{s.embed_model} unavailable: using the fake embedder")
            embedder = FakeEmbedder()
    from aura.ingest.parsers import FormatRegistryParser, limits_from_settings
    limits = replace(limits_from_settings(), scan_vlm=args.scan_vlm or "off")
    cases, digest = load_golden("retrieval", args.limit)
    with SessionLocal() as session:
        run = evaluate_retrieval(session, embedder, cases, digest,
                                 s.eval_threshold_retrieval,
                                 parser=FormatRegistryParser(limits), packs=ALL_PACKS)
    m = run.metrics
    for case in run.cases:
        rank = case.detail.get("first_relevant_rank")
        top = case.actual["top"][0] if case.actual["top"] else {}
        print(f"  {case.case_id}  rank={rank if rank else '-':<3} "
              f"{case.latency_ms:>5} ms  top: {top.get('filename', '-')} "
              f"p{top.get('pages')}")
    print(f"retrieval  model={run.model_id}  n={run.n_cases}  recall@5={m['recall_at_5']:.2f}"
          f"  MRR={m['mrr']:.3f}  index={m['index_seconds']}s  "
          f"mean query={m['mean_query_ms']} ms  chunks={m['chunks']}  "
          f"ocr={','.join(m['ocr_used']) or '-'}  pdf_parser={limits.pdf_parser}  "
          f"scan_vlm={limits.scan_vlm}  run #{run.id}")
    for name, sub in m.get("subsets", {}).items():
        print(f"  subset {name:<8} n={sub['n']:<3} recall@5={sub['recall_at_5']:.2f}  "
              f"MRR={sub['mrr']:.3f}")
    if not run.passed:
        print(f"BELOW THRESHOLD: retrieval recall@5 {run.score:.2f} < {run.threshold:.2f}")
        return 1
    return 0


def run_parsing(args) -> int:
    """Parse and score the Kaveri fixtures with one or both PDF parsers. Stored as eval_run
    rows (capability 'parsing') when the database is up; exit 1 when the parser the settings
    would use scores below eval_threshold_parsing."""
    from aura.evals.parsing import evaluate_parser, load_ground_truth, report, to_eval_run
    from aura.ingest.docling_parser import docling_available
    from aura.ingest.parsers import resolve_pdf_parser
    s = get_settings()
    configured = resolve_pdf_parser(s.pdf_parser, s.docling_artifacts)
    choice = args.pdf_parser or ("both" if docling_available(s.docling_artifacts)
                                 else "pymupdf")
    parsers = ["pymupdf", "docling"] if choice == "both" else [choice]
    gating = configured if configured in parsers else parsers[0]
    scan_vlm = args.scan_vlm or "off"
    threshold = s.eval_threshold_parsing
    gt, digest = load_ground_truth()
    runs = {}
    for name in parsers:
        started = utcnow()
        result = evaluate_parser(name, scan_vlm, gt)
        print(report(name, result))
        runs[name] = to_eval_run(name, scan_vlm, result, digest, threshold, started)
    stored = _store_runs(list(runs.values()))
    for name, run in runs.items():
        print(f"parsing  parser={name:<8} scan_vlm={scan_vlm}  score={run.score:.3f}  "
              f"thresh={threshold:.2f}  {'pass' if run.passed else 'FAIL'}"
              f"{'  (gating: settings use it)' if name == gating else ''}"
              f"{f'  run #{run.id}' if stored else ''}")
    if not stored:
        print("(not stored: the database or its eval tables are not available)")
    gate = runs[gating]
    if not gate.passed:
        print(f"BELOW THRESHOLD: parsing ({gating}) {gate.score:.3f} < {threshold:.2f}")
        return 1
    return 0


def _store_runs(runs: list[EvalRun]) -> bool:
    """Store eval runs when the database has the eval tables (sets their ids)."""
    try:
        from aura.data.engine import SessionLocal, engine
        from aura.data.repositories.sql_harness import SqlEvalRepository
        if not inspect(engine).has_table("eval_run"):
            return False
        with SessionLocal() as session:
            repo = SqlEvalRepository(session)
            for run in runs:
                run.id = repo.add_run(run).id
            session.commit()
        return True
    except Exception as exc:  # the scores are still printed; storage is best effort
        print(f"could not store the parsing runs: {type(exc).__name__}: {exc}",
              file=sys.stderr)
        return False


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
             threshold: float | None = None, created_by: str = "cli",
             case_ids: set[str] | None = None) -> EvalRun:
    """Run, score and store one capability's golden set. Commits. A run over part of the
    set (`limit` or `case_ids`) is stored with metrics.partial = true: it is shown, but
    autonomy promotion and demotion ignore it."""
    from aura.data.repositories.sql_harness import SqlEvalRepository
    from aura.data.run_sink import SqlAgentRunSink
    from aura.data.spans import flush_spans

    s = get_settings()
    limits = ContextLimits(max_chars=s.max_context_chars, excerpt_chars=s.context_excerpt_chars,
                           retrieval_top_k=0, injection_threshold=s.injection_risk_threshold)
    cases, digest = load_golden(capability, limit, case_ids)
    partial = len(cases) < len(load_golden(capability)[0])
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
        if partial:
            metrics.update({"partial": True, "case_ids": [c.get("id") for c in cases]})
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
                        choices=[*EVAL_CAPABILITIES, "retrieval", "parsing", "intake", "all"])
    parser.add_argument("--orchestrator", choices=["stub", "crew"], default="stub")
    parser.add_argument("--limit", type=int, default=None, help="cases per capability")
    parser.add_argument("--cases", default=None,
                        help="comma-separated golden case ids (e.g. cls-015,cls-016); a "
                             "partial run is stored but not used for autonomy")
    parser.add_argument("--embedder", choices=["auto", "ollama", "fake"], default="auto",
                        help="retrieval only: auto uses Ollama when it answers")
    parser.add_argument("--pdf-parser", choices=["pymupdf", "docling", "both"], default=None,
                        help="parsing only: default both when Docling is installed")
    parser.add_argument("--scan-vlm", choices=["off", "fallback", "always"], default=None,
                        help="parsing and retrieval: vision model for scanned pages "
                             "(default off)")
    parser.add_argument("--llm", choices=["auto", "ollama", "off"], default="auto",
                        help="intake only: the local model (auto: when Ollama answers) or "
                             "deterministic extraction only")
    args = parser.parse_args(argv)
    if args.capability == "parsing":
        return run_parsing(args)
    if args.capability == "intake":
        from aura.evals.intake import run as run_intake
        tracer.configure(get_settings().tracing_enabled)
        return run_intake(args.llm)[0]

    from aura.data.engine import SessionLocal, engine
    if not inspect(engine).has_table("eval_run"):
        print("The database has no eval tables yet: run `uv run alembic upgrade head` (or "
              "start the API once).", file=sys.stderr)
        return 2
    tracer.configure(get_settings().tracing_enabled)
    if args.capability == "retrieval":
        return run_retrieval(args)
    orchestrator, model_id = make_orchestrator(args.orchestrator)
    capabilities = list(EVAL_CAPABILITIES) if args.capability == "all" else [args.capability]
    case_ids = {c.strip() for c in args.cases.split(",") if c.strip()} if args.cases else None
    if case_ids:
        capabilities = [c for c in capabilities if load_golden(c, None, case_ids)[0]]
        if not capabilities:
            print(f"No golden case matches --cases {args.cases}", file=sys.stderr)
            return 2
    runs = []
    with SessionLocal() as session:
        for capability in capabilities:
            runs.append(evaluate(capability, orchestrator, args.orchestrator, model_id,
                                 session, args.limit, case_ids=case_ids))
    print(summary_table(runs))
    failed = [r.capability for r in runs if not r.passed]
    if failed:
        print(f"BELOW THRESHOLD: {', '.join(failed)}")
        return 1
    print("All capabilities at or above their thresholds.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
