"""Deal-intake extraction eval (`python -m aura.evals.run --capability intake`).

Each golden pack (evals/golden/intake.json: the Project Kaveri and Project Nilgiri fixtures)
is parsed with the configured parser, chunked, embedded and searched in memory with the same
hybrid search (aura.core.services.search) the worker uses, then extracted by
aura.core.services.intake_extraction - with the live local model (--llm ollama, the default
when Ollama answers) or deterministic extractors only (--llm off, what the tests use). Reported:

- per-field accuracy and per field-group accuracy against the expected values;
- citation validity: a filled field's first citation points at a chunk that really holds the
  value (the number as written in the cited unit, the identifier, the text);
- conflict detection: a doctored extra document stating a different FY24 revenue must raise a
  revenue conflict, and the clean pack must raise none on the expected fields;
- time per pack (parse + index, extraction).

Model calls are recorded in agent_run (archetype 'eval:intake_extractor', no deal, no intake).
Not an agent capability: the run is stored as eval_run 'intake' and never touches autonomy.
"""
import hashlib
import json
import math
import time
from dataclasses import dataclass, replace
from pathlib import Path

from aura.config import BACKEND_DIR, get_settings
from aura.core.clock import utcnow
from aura.core.domain.harness import EvalCaseResult, EvalRun
from aura.core.domain.ingest import ChunkHit
from aura.core.domain.intake import StagedChunk
from aura.core.services import intake_fields as F
from aura.core.services.chunking import ChunkingParams, chunk_document
from aura.core.services.intake import schema_for
from aura.core.services.intake_extraction import (ExtractionSettings, LLM_GROUPS,
                                                  GROUP_FIELDS, run_extraction)
from aura.core.services.search import SearchParams, search

GOLDEN = BACKEND_DIR / "evals" / "golden" / "intake.json"


class MemoryChunks:
    """ChunkRepository over a list of chunks: cosine distance and a term-overlap score."""

    def __init__(self, chunks: list[StagedChunk], vectors: list[list[float]]):
        self.chunks, self.vectors = chunks, vectors

    def _hit(self, c: StagedChunk, **kw) -> ChunkHit:
        return ChunkHit(chunk_id=c.chunk_id, document_id=c.document_id, filename=c.filename,
                        version=1, chunk_index=c.chunk_id, text=c.text, kind=c.kind,
                        page_from=c.page_from, page_to=c.page_to, **kw)

    def vector_search(self, deal_id, vector, limit, ef_search=80):
        def dist(v):
            dot = sum(a * b for a, b in zip(v, vector))
            na = math.sqrt(sum(a * a for a in v)) or 1.0
            nb = math.sqrt(sum(b * b for b in vector)) or 1.0
            return 1 - dot / (na * nb)
        scored = sorted(((dist(v), c) for c, v in zip(self.chunks, self.vectors)),
                        key=lambda t: (t[0], t[1].chunk_id))
        return [self._hit(c, distance=d) for d, c in scored[:limit]]

    def text_search(self, deal_id, query, limit):
        terms = {t for t in query.lower().split() if len(t) > 2}
        scored = []
        for c in self.chunks:
            low = c.text.lower()
            score = sum(1 for t in terms if t in low)
            if score:
                scored.append((score, c))
        scored.sort(key=lambda t: (-t[0], t[1].chunk_id))
        return [self._hit(c, fts_score=float(s)) for s, c in scored[:limit]]


def load_golden() -> tuple[dict, str]:
    text = GOLDEN.read_text(encoding="utf-8").replace("\r\n", "\n")
    return json.loads(text), hashlib.sha256(text.encode()).hexdigest()


def parse_pack(pack: dict, parser, extra: list[tuple[str, bytes]] = (),
               chunks: list[StagedChunk] | None = None) -> tuple[list, float]:
    """Parse and chunk the pack's files (or, with `chunks`, only `extra`, appended)."""
    s = get_settings()
    started = time.perf_counter()
    base = BACKEND_DIR / pack["dir"]
    if chunks is None:
        chunks = []
        files = [(n, (base / n).read_bytes()) for n in pack["files"]] + list(extra)
    else:
        chunks = list(chunks)
        files = list(extra)
    first_doc = max((c.document_id for c in chunks), default=0) + 1
    for doc_id, (name, content) in enumerate(files, start=first_doc):
        parsed = parser.parse(content, name)
        for d in chunk_document(parsed, ChunkingParams(s.chunk_target_tokens,
                                                       s.chunk_overlap_tokens)):
            meta = dict(d.meta)
            if d.heading:
                meta["heading"] = d.heading
            chunks.append(StagedChunk(chunk_id=len(chunks) + 1, document_id=doc_id,
                                      filename=name, page_from=d.page_from, page_to=d.page_to,
                                      kind=d.kind, text=d.text, meta=meta))
    return chunks, time.perf_counter() - started


def _matches(spec: F.FieldSpec, expected: dict, actual) -> bool:
    if actual is None:
        return False
    if "equals" in expected:
        want = expected["equals"]
        if spec.type in ("inr", "number", "percent", "integer"):
            return isinstance(actual, (int, float)) and F.same_value(spec, float(actual),
                                                                     float(want))
        return F.same_value(spec, str(actual), str(want))
    if "contains" in expected:
        return expected["contains"].lower() in str(actual).lower()
    if "includes" in expected:
        got = {(f.get("flag") if isinstance(f, dict) else f) for f in actual or []}
        return set(expected["includes"]) <= got
    return False


def _value_strings(spec: F.FieldSpec, value) -> list[str]:
    """How the value would be written in a document."""
    if spec.type == "inr" and isinstance(value, (int, float)):
        out = []
        for factor in (10_000_000, 100_000, 1_000_000, 1):
            v = value / factor
            out += [f"{v:.2f}", f"{v:g}", f"{v:,.2f}", f"{v:.1f}"]
        return out
    if spec.type in ("number", "percent", "integer") and isinstance(value, (int, float)):
        return [f"{value:g}", f"{value:.2f}"]
    if spec.type == "flags" and value:
        return [str(value[0].get("reason") or "")[:40]]
    if isinstance(value, list):
        return [str(v.get("name") if isinstance(v, dict) else v)[:40] for v in value[:1]]
    text = str(value)
    return [text, text[:25]]


def citation_valid(spec: F.FieldSpec, record: dict, by_id: dict[int, StagedChunk]) -> bool:
    cites = record.get("citations") or []
    if not cites:
        return False
    chunk = by_id.get(cites[0]["chunk_id"])
    if chunk is None or chunk.page_from != cites[0]["page_from"]:
        return False
    if spec.type == "enum" and spec.key == "transaction_class":
        return True   # a category, not a string in the text: the cited passage is its signal
    flat = " ".join(chunk.text.split()).lower()
    return any(s.lower() in flat for s in _value_strings(spec, record.get("value")) if s)


def _embed(embedder, texts: list[str]) -> list[list[float]]:
    """Embed in batches; when the model fails, the deterministic hash vectors stand in (the
    eval then measures keyword retrieval, and says so in its metrics)."""
    from aura.ingest.embedder import FakeEmbedder
    out: list[list[float]] = []
    for i in range(0, len(texts), 16):
        group = texts[i:i + 16]
        try:
            out += embedder.embed(group, kind="document")
        except Exception:
            out += FakeEmbedder(getattr(embedder, "dimensions", 768)).embed(group)
    return out


@dataclass
class PackResult:
    pack: str
    fields: dict[str, dict]
    index_s: float
    extract_s: float
    llm_used: bool
    conflicts_on_expected: list[str]
    probe_detected: bool | None
    warnings: list[str]


def evaluate_pack(pack: dict, parser, embedder, extractor) -> PackResult:
    chunks, index_s = parse_pack(pack, parser)
    vectors = _embed(embedder, [c.text for c in chunks])
    store = MemoryChunks(chunks, vectors)

    def retriever(store):
        def retrieve(query, k):
            return [r.chunk_id for r in search(0, query, store, embedder,
                                               SearchParams(k=k)).results]
        return retrieve

    s = get_settings()
    settings = ExtractionSettings(threshold=s.intake_confidence_threshold, top_k=s.intake_top_k,
                                  context_chars=s.intake_context_chars)
    started = time.perf_counter()
    result = run_extraction(chunks, retriever(store), extractor, schema_for, settings=settings)
    extract_s = time.perf_counter() - started
    by_id = {c.chunk_id: c for c in chunks}
    specs = {sp.key: sp for sp in F.specs_for(schema_for(result.transaction_class))}
    fields = {}
    for key, expected in pack["expected"].items():
        spec = specs.get(key) or F.BASE_BY_KEY.get(key)
        rec = result.fields.get(key) or {}
        ok = spec is not None and _matches(spec, expected, rec.get("value"))
        fields[key] = {"expected": expected, "actual": rec.get("value"),
                       "correct": ok, "source": rec.get("source"),
                       "confidence": rec.get("confidence"),
                       "citation_valid": bool(spec and rec.get("value") is not None
                                              and citation_valid(spec, rec, by_id))}
    conflicts = [c["field"] for c in result.conflicts if c["field"] in pack["expected"]]
    probe = None
    if pack.get("probe_conflict"):
        p = pack["probe_conflict"]
        extra = [(p["filename"], p["text"].encode("utf-8"))]
        pchunks, _ = parse_pack(pack, parser, extra, chunks)
        pvectors = vectors + _embed(embedder, [c.text for c in pchunks[len(chunks):]])
        presult = run_extraction(pchunks, retriever(MemoryChunks(pchunks, pvectors)), None,
                                 schema_for, settings=settings)
        probe = any(c["field"] == p["field"] for c in presult.conflicts)
    return PackResult(pack["id"], fields, round(index_s, 1), round(extract_s, 1),
                      result.llm_used, conflicts, probe, result.warnings)


def group_of(key: str) -> str:
    if key.startswith(F.PROFILE_PREFIX):
        return "profile"
    for group, keys in GROUP_FIELDS.items():
        if key in keys:
            return group
    return "other"


def summarise(results: list[PackResult]) -> dict:
    rows = [(r.pack, k, v) for r in results for k, v in r.fields.items()]
    groups: dict[str, list[bool]] = {}
    for _, key, v in rows:
        groups.setdefault(group_of(key), []).append(v["correct"])
    filled = [v for _, _, v in rows if v["actual"] is not None]
    probes = [r.probe_detected for r in results if r.probe_detected is not None]
    return {
        "field_accuracy": round(sum(v["correct"] for _, _, v in rows) / max(1, len(rows)), 4),
        "group_accuracy": {g: round(sum(v) / len(v), 4) for g, v in
                           sorted(groups.items(), key=lambda kv: LLM_GROUPS.index(kv[0])
                                  if kv[0] in LLM_GROUPS else 99)},
        "citation_validity": round(sum(v["citation_valid"] for v in filled)
                                   / max(1, len(filled)), 4),
        "conflict_probe_detected": all(probes) if probes else None,
        "false_conflicts": sum(len(r.conflicts_on_expected) for r in results),
        "packs": {r.pack: {"index_s": r.index_s, "extract_s": r.extract_s,
                           "llm_used": r.llm_used,
                           "accuracy": round(sum(v["correct"] for v in r.fields.values())
                                             / max(1, len(r.fields)), 4),
                           "conflicts_on_expected": r.conflicts_on_expected,
                           "warnings": r.warnings[:5]} for r in results},
    }


def to_eval_run(results: list[PackResult], metrics: dict, digest: str, model_id: str,
                orchestrator: str, threshold: float, started) -> EvalRun:
    cases = [EvalCaseResult(id=None, eval_run_id=None, case_id=f"{r.pack}:{k}"[:64],
                            passed=v["correct"], score=1.0 if v["correct"] else 0.0,
                            confidence=v["confidence"], expected=v["expected"],
                            actual={"value": v["actual"], "source": v["source"]},
                            detail={"citation_valid": v["citation_valid"]})
             for r in results for k, v in r.fields.items()]
    score = metrics["field_accuracy"]
    return EvalRun(id=None, capability="intake", orchestrator=orchestrator, model_id=model_id,
                   golden_sha256=digest, n_cases=len(cases), score=score, threshold=threshold,
                   passed=score >= threshold, metrics=metrics, started_at=started,
                   completed_at=utcnow(), cases=cases)


def report(results: list[PackResult], metrics: dict) -> str:
    lines = []
    for r in results:
        lines.append(f"pack {r.pack}: index {r.index_s}s  extract {r.extract_s}s  "
                     f"model={'yes' if r.llm_used else 'no'}")
        for key, v in r.fields.items():
            mark = "ok " if v["correct"] else "BAD"
            cite = "cite-ok" if v["citation_valid"] else ("cite-BAD" if v["actual"] is not None
                                                          else "-")
            lines.append(f"  {mark} {key:<24} {str(v['actual'])[:44]:<46} "
                         f"{v['source'] or '-':<6} {cite}")
    lines.append("groups: " + "  ".join(f"{g}={a:.2f}" for g, a in
                                        metrics["group_accuracy"].items()))
    lines.append(f"field accuracy={metrics['field_accuracy']:.3f}  citation validity="
                 f"{metrics['citation_validity']:.3f}  conflict probe="
                 f"{metrics['conflict_probe_detected']}  false conflicts="
                 f"{metrics['false_conflicts']}")
    return "\n".join(lines)


def run(llm: str = "auto", parser=None, embedder=None, store: bool = True) -> tuple[int, dict]:
    """The eval as `python -m aura.evals.run --capability intake` runs it. Returns (exit
    code, metrics)."""
    import sys
    s = get_settings()
    golden, digest = load_golden()
    if parser is None:
        from aura.ingest.parsers import FormatRegistryParser, limits_from_settings
        parser = FormatRegistryParser(replace(limits_from_settings(), scan_vlm="off"))
    if embedder is None:
        from aura.ingest.embedder import FakeEmbedder, OllamaEmbedder, embedder_available
        embedder = OllamaEmbedder(s.ollama_base_url, s.embed_model, s.embed_batch,
                                  s.embed_timeout_seconds, s.embed_max_retries)
        if not embedder_available(embedder):
            embedder = FakeEmbedder()
    extractor, model_id, sink = None, "deterministic", None
    if llm in ("auto", "ollama"):
        from aura.agents.llm.ollama_check import model_digest, ollama_available
        if ollama_available(s.ollama_base_url) or llm == "ollama":
            digest_model = model_digest(s.ollama_base_url, s.ollama_model)
            from aura.agents.llm.intake_extractor import OllamaFieldExtractor
            from aura.agents.llm.recording import RunRecorder
            from aura.core.ports.orchestrator import RunContext
            sink = _sink()
            recorder = RunRecorder(RunContext(job_id=None, deal_id=None, task_id=None,
                                              runs=sink, archetype_prefix="eval:"),
                                   s.ollama_model, digest_model or "unknown",
                                   max_calls=100, max_seconds=7200)
            extractor = OllamaFieldExtractor(recorder, s.ollama_base_url, s.ollama_model,
                                             s.intake_llm_timeout_s, s.intake_llm_num_ctx,
                                             s.ollama_think)
            model_id = s.ollama_model
    started = utcnow()
    results = [evaluate_pack(p, parser, embedder, extractor) for p in golden["packs"]]
    metrics = summarise(results)
    metrics["embedder"] = getattr(embedder, "model", "?")
    if sink is not None:
        sink.flush()
    threshold = s.eval_threshold_intake
    print(report(results, metrics))
    eval_run = to_eval_run(results, metrics, digest, model_id,
                           "crew" if extractor else "stub", threshold, started)
    if store:
        from aura.evals.run import _store_runs
        stored = _store_runs([eval_run])
        print(f"intake  model={model_id}  score={eval_run.score:.3f}  thresh={threshold:.2f}  "
              f"{'pass' if eval_run.passed else 'FAIL'}"
              f"{f'  run #{eval_run.id}' if stored else '  (not stored)'}")
    if not eval_run.passed:
        print(f"BELOW THRESHOLD: intake field accuracy {eval_run.score:.3f} < "
              f"{threshold:.2f}", file=sys.stderr)
        return 1, metrics
    return 0, metrics


class _sink:
    """agent_run rows for the eval's model calls, written in one transaction at the end."""

    def __init__(self):
        self.runs = []

    def record(self, run):
        self.runs.append(run)
        return run

    def flush(self):
        try:
            from aura.data.engine import SessionLocal
            from aura.data.repositories.sql import SqlAgentRunRepository
            from aura.data.walls import SYSTEM
            with SessionLocal() as session:
                repo = SqlAgentRunRepository(session, SYSTEM)
                for r in self.runs:
                    repo.add(r)
                session.commit()
        except Exception as exc:  # lineage is best effort when no database is up
            print(f"could not record the eval's model runs: {exc}")
