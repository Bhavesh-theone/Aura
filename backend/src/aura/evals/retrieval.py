"""Retrieval evaluation: hybrid search over the fixture deal packs, scored on a golden set.

    uv run python -m aura.evals.run --capability retrieval [--embedder ollama|fake]
        [--scan-vlm off|fallback|always]

The fixture packs (tests/fixtures/ingest, the fictional "Project Nilgiri": PDF with a scanned
page, DOCX, XLSX, PPTX, EML, Markdown, CSV; and tests/fixtures/parsing, "Project Kaveri":
digital and scanned PDFs with financial tables, DOCX, XLSX, PPTX) are parsed, chunked and
embedded by the real pipeline into one throwaway deal, inside one transaction that is rolled
back at the end: the database keeps only the eval_run row. Golden cases whose expected files
are in none of the indexed packs are skipped (evaluate_retrieval indexes only the Nilgiri pack
unless told otherwise; the CLI indexes both). Metrics are also split by subset: ret-* cases
(Nilgiri) and kav-* cases (Kaveri). Each golden query (evals/golden/retrieval.jsonl) is
searched with the real hybrid search; a result is relevant when it comes from an expected file
and (if given) contains the expected phrase. Metrics: recall@5 (a relevant chunk in the top
5) and MRR (mean reciprocal rank of the first relevant chunk, over the top k).
"""
import hashlib
import time
from pathlib import Path

from sqlalchemy.orm import Session

from aura.config import BACKEND_DIR, get_settings
from aura.core.clock import utcnow
from aura.core.domain.harness import EvalCaseResult, EvalRun
from aura.core.domain.ingest import IndexJob
from aura.core.services.chunking import ChunkingParams
from aura.core.services.indexing import IndexSettings, index_document
from aura.core.services.search import SearchParams, search
from aura.core.tracing import tracer

FIXTURE_DIR = BACKEND_DIR / "tests" / "fixtures" / "ingest"
PACK = ("nilgiri_information_memorandum.pdf", "nilgiri_spa_draft.docx",
        "nilgiri_financial_model.xlsx", "nilgiri_management_presentation.pptx",
        "nilgiri_fdd_red_flags.eml", "nilgiri_board_minutes.md", "nilgiri_dd_tracker.csv")
KAVERI_DIR = BACKEND_DIR / "tests" / "fixtures" / "parsing"
KAVERI_PACK = ("kaveri_audited_financials_fy24.pdf", "kaveri_ncd_term_sheet.pdf",
               "kaveri_borrowings_schedule_scanned.pdf", "kaveri_board_resolution_scanned.pdf",
               "kaveri_information_memorandum.docx", "kaveri_financial_model.xlsx",
               "kaveri_teaser.pptx")
PACKS = {"nilgiri": (FIXTURE_DIR, PACK), "kaveri": (KAVERI_DIR, KAVERI_PACK)}
ALL_PACKS = ("nilgiri", "kaveri")
SUBSETS = {"ret": "nilgiri", "kav": "kaveri"}  # case-id prefix -> subset name
EVAL_EXTERNAL_ID = "EVAL-RETRIEVAL"
K = 10


class _NoAudit:
    def append(self, entry):
        return entry


def relevant(result, case: dict) -> bool:
    for exp in case["expected"]:
        if result.filename == exp["filename"] and (
                not exp.get("contains") or exp["contains"].lower() in result.text.lower()):
            return True
    return False


def score_case(results, case: dict, k_recall: int = 5) -> dict:
    first = next((r.rank for r in results if relevant(r, case)), None)
    return {"first_relevant_rank": first,
            "hit_at_5": first is not None and first <= k_recall,
            "reciprocal_rank": 1.0 / first if first else 0.0}


def pack_files(packs=("nilgiri",), fixture_dir: Path = FIXTURE_DIR) -> list[tuple[Path, str]]:
    """(directory, filename) of every file in these packs; `fixture_dir` replaces Nilgiri's."""
    out = []
    for pack in packs:
        directory, names = PACKS[pack]
        directory = fixture_dir if pack == "nilgiri" else directory
        out += [(directory, name) for name in names]
    return out


def build_pack(session: Session, embedder, owner: str, fixture_dir: Path = FIXTURE_DIR,
               parser=None, packs=("nilgiri",)) -> tuple[int, dict]:
    """Index the fixture packs into a new deal on this session (the caller rolls back).
    Returns (deal_id, per-file summary)."""
    from aura.data.models.tables import DealRow, DocumentRow
    from aura.data.repositories.sql_deals import SqlDocumentRepository
    from aura.data.repositories.sql_ingest import SqlChunkRepository
    from aura.data.walls import SYSTEM, bind_viewer
    from aura.ingest.parsers import FormatRegistryParser
    from sqlalchemy import text
    bind_viewer(session, SYSTEM)
    # One transaction holds the whole pack (it is rolled back); OCR and embedding run inside
    # it, so the server must not end it as idle (aura_test sets a 3 s limit).
    session.execute(text("SET LOCAL idle_in_transaction_session_timeout = 0"))
    now = utcnow()
    deal = DealRow(external_id=EVAL_EXTERNAL_ID, name="Retrieval evaluation (fixture packs)",
                   stage="DILIGENCE", transaction_class="MNA", owner=owner,
                   opened_at=now)
    session.add(deal)
    session.flush()
    contents: dict[str, bytes] = {}
    documents = SqlDocumentRepository(session, SYSTEM)
    chunks = SqlChunkRepository(session, SYSTEM)
    parser = parser or FormatRegistryParser()
    s = get_settings()
    settings = IndexSettings(ChunkingParams(s.chunk_target_tokens, s.chunk_overlap_tokens),
                             s.embed_batch)
    summary = {}
    for directory, name in pack_files(packs, fixture_dir):
        content = (directory / name).read_bytes()
        sha = hashlib.sha256(content).hexdigest()
        contents[sha] = content
        row = DocumentRow(deal_id=deal.id, doc_class="nda", filename=name, sha256=sha,
                          byte_size=len(content), current_version=1, contains_upsi=False,
                          sensitivity=2, uploaded_by=owner, uploaded_at=now)
        session.add(row)
        session.flush()
        job = IndexJob(id=None, document_id=row.id, deal_id=deal.id, version=1,
                       status="running")
        t0 = time.perf_counter()
        summary[name] = index_document(job, documents, contents.__getitem__, parser,
                                       embedder, chunks, documents, _NoAudit(), None,
                                       settings)
        summary[name]["seconds"] = round(time.perf_counter() - t0, 2)
    return deal.id, summary


def subset_of(case_id: str) -> str:
    return SUBSETS.get(case_id.split("-", 1)[0], "other")


def subset_metrics(results: list[EvalCaseResult]) -> dict:
    groups: dict[str, list[EvalCaseResult]] = {}
    for r in results:
        groups.setdefault(subset_of(r.case_id), []).append(r)
    return {name: {"n": len(rs),
                   "recall_at_5": round(sum(1 for r in rs if r.passed) / len(rs), 4),
                   "mrr": round(sum(r.score for r in rs) / len(rs), 4)}
            for name, rs in groups.items()}


def evaluate_retrieval(session: Session, embedder, cases: list[dict], digest: str,
                       threshold: float, created_by: str = "cli", store: bool = True,
                       parser=None, packs=("nilgiri",)) -> EvalRun:
    """Index `packs`, search every golden case whose expected files are among them, score and
    (by default) store the run. `parser` replaces the configured FormatRegistryParser."""
    from aura.data.repositories.sql_ingest import SqlChunkRepository
    from aura.data.walls import SYSTEM
    s = get_settings()
    params = SearchParams(k=K, candidates=s.search_candidates, rrf_k=s.rrf_k,
                          ef_search=s.hnsw_ef_search)
    owner = "admin"
    indexed = {name for _, name in pack_files(packs)}
    skipped = [c["id"] for c in cases
               if not any(e["filename"] in indexed for e in c["expected"])]
    cases = [c for c in cases if c["id"] not in skipped]
    started = utcnow()
    clock = time.perf_counter()
    results: list[EvalCaseResult] = []
    with tracer.span("eval.run", {"aura.capability": "retrieval",
                                  "gen_ai.request.model": embedder.model}) as span:
        try:
            deal_id, pack = build_pack(session, embedder, owner, parser=parser,
                                       packs=packs)
            index_seconds = round(time.perf_counter() - clock, 2)
            repo = SqlChunkRepository(session, SYSTEM)
            for case in cases:
                t0 = time.perf_counter()
                response = search(deal_id, case["query"], repo, embedder, params)
                scored = score_case(response.results, case)
                results.append(EvalCaseResult(
                    id=None, eval_run_id=None, case_id=case["id"],
                    passed=bool(scored["hit_at_5"]), score=scored["reciprocal_rank"],
                    confidence=None, expected={"expected": case["expected"]},
                    actual={"top": [{"rank": r.rank, "filename": r.filename,
                                     "chunk": r.chunk_index, "pages": [r.page_from, r.page_to],
                                     "score": r.score} for r in response.results[:5]],
                            "mode": response.mode},
                    detail=scored, latency_ms=int((time.perf_counter() - t0) * 1000)))
        finally:
            session.rollback()  # the pack never persists
    n = len(results) or 1
    recall = sum(1 for r in results if r.passed) / n
    mrr = sum(r.score for r in results) / n
    metrics = {"primary": "recall_at_5", "recall_at_5": round(recall, 4),
               "mrr": round(mrr, 4), "k": K, "index_seconds": index_seconds,
               "total_latency_ms": sum(r.latency_ms for r in results),
               "mean_query_ms": round(sum(r.latency_ms for r in results) / n, 1),
               "chunks": sum(v["chunks"] for v in pack.values()),
               "ocr_used": [k for k, v in pack.items() if v["ocr_used"]],
               "embedding_model": embedder.model, "trace_id": span.trace_id,
               "errors": 0, "packs": list(packs), "subsets": subset_metrics(results)}
    if skipped:
        metrics["skipped_cases"] = skipped
    run = EvalRun(id=None, capability="retrieval", orchestrator="search",
                  model_id=embedder.model, golden_sha256=digest, n_cases=len(results),
                  score=recall, threshold=threshold, passed=recall >= threshold,
                  metrics=metrics, started_at=started, completed_at=utcnow(),
                  created_by=created_by, cases=results)
    if store:
        from aura.data.repositories.sql_harness import SqlEvalRepository
        run = SqlEvalRepository(session).add_run(run)
        session.commit()
    return run
