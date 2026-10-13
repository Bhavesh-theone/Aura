"""Parsing evaluation: how faithfully the parsers read the 'Project Kaveri' fixture pack.

    uv run python -m aura.evals.run --capability parsing [--pdf-parser pymupdf|docling|both]
        [--scan-vlm off|fallback|always]

Every document of tests/fixtures/parsing (digital and scanned PDFs, DOCX, XLSX, PPTX; generated
by make_kaveri.py from the same element lists as ground_truth.json) is parsed with
aura.ingest.parsers.parse, using the configured limits with the PDF parser and scan VLM mode
replaced. Scored per document (the semantics of the parser bake-off, docs/research/
parser-bakeoff.md, so the numbers are comparable):

- CER: character edit distance / reference length, on whitespace- and quote-normalised text;
- table-cell accuracy: for each ground-truth table, the best predicted table's matched
  non-empty cells (order-preserving, per best-matching row) / ground-truth non-empty cells;
- row integrity: ground-truth rows found as one contiguous token run (a table row or a block);
- row/col fields: a value found in the right row and column of a predicted table;
- key-field recall: an expected value (any of its spellings) appears in the text;
- heading recall: ground-truth headings matched by a predicted heading block.

Non-PDF documents are parsed the same way whatever the PDF parser; they are scored too, so the
totals cover the whole pack. Score = mean(table-cell accuracy, row/col field accuracy,
key-field recall) over the pack, for the parser the settings would use.
"""
import hashlib
import json
import time
import unicodedata
from collections import Counter
from dataclasses import replace
from difflib import SequenceMatcher

from aura.config import BACKEND_DIR

FIXTURE_DIR = BACKEND_DIR / "tests" / "fixtures" / "parsing"
GROUND_TRUTH = FIXTURE_DIR / "ground_truth.json"
FINANCIAL_DOC = "kaveri_audited_financials_fy24.pdf"


def load_ground_truth() -> tuple[dict, str]:
    """(ground truth, sha256 of the file with LF line endings)."""
    text = GROUND_TRUTH.read_text(encoding="utf-8").replace("\r\n", "\n")
    return json.loads(text), hashlib.sha256(text.encode()).hexdigest()


# ------------------------------------------------------------------ normalisation
_TRANS = str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"',
                        "–": "-", "—": "-", "\xa0": " "})


def norm(s: str | None) -> str:
    s = unicodedata.normalize("NFKC", s or "").translate(_TRANS)
    return " ".join(s.split())


def ncell(s) -> str:
    return norm(str(s).replace("**", "")).replace("₹ ", "₹").strip()


def row_cells(row) -> list[str]:
    out = []
    for c in row:
        c = ncell(c)
        if c and (not out or out[-1] != c):  # colspan repeats collapse
            out.append(c)
    return out


def _is_table(b: dict) -> bool:
    return b["kind"] == "table" and bool(b.get("rows"))


def block_text(b: dict) -> str:
    if _is_table(b):
        return "\n".join(" ".join(row_cells(r)) for r in b["rows"] if row_cells(r))
    return b.get("text") or ""


def doc_text(blocks: list[dict]) -> str:
    return norm("\n".join(block_text(b) for b in blocks))


# ------------------------------------------------------------------ metrics
def levenshtein(a: str, b: str) -> int:
    """Edit distance (insert, delete, substitute: cost 1), two-row dynamic programming."""
    start = 0
    while start < len(a) and start < len(b) and a[start] == b[start]:
        start += 1
    a, b = a[start:], b[start:]
    while a and b and a[-1] == b[-1]:
        a, b = a[:-1], b[:-1]
    if len(a) < len(b):
        a, b = b, a
    if not b:
        return len(a)
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1,
                               previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


def cer(reference: str, hypothesis: str) -> float:
    return levenshtein(reference, hypothesis) / len(reference) if reference else 0.0


def lcs(a: list, b: list) -> int:
    return sum(m.size for m in SequenceMatcher(None, a, b, autojunk=False)
               .get_matching_blocks())


def table_score(gt_grid, blocks: list[dict]) -> dict:
    gt_rows = [r for r in (row_cells(r) for r in gt_grid) if r]
    total = sum(len(r) for r in gt_rows)
    best, best_block = 0, None
    for b in blocks:
        if not _is_table(b):
            continue
        pred = [row_cells(r) for r in b["rows"]]
        got = sum(max((lcs(g, p) for p in pred), default=0) for g in gt_rows)
        if got > best:
            best, best_block = got, b
    return {"cells_total": total, "cells_matched": best,
            "cell_accuracy": round(best / total, 4) if total else None,
            "table_found": best_block is not None,
            "pred_rows": len(best_block["rows"]) if best_block else 0, "gt_rows": len(gt_rows)}


def units(blocks: list[dict]) -> list[list[str]]:
    """Token lists a ground-truth row may sit in: each predicted table row, each text block."""
    out = []
    for b in blocks:
        if _is_table(b):
            out += [" ".join(row_cells(r)).split() for r in b["rows"]]
        else:
            out.append(norm(b.get("text")).split())
    return out


def _contiguous(needle: list, hay: list) -> bool:
    n = len(needle)
    return any(hay[i:i + n] == needle for i in range(len(hay) - n + 1)) if n else False


def row_integrity(gt_grid, us: list[list[str]]) -> tuple[int, int]:
    rows = [r for r in (" ".join(row_cells(r)).split() for r in gt_grid) if r]
    return sum(1 for r in rows if any(_contiguous(r, u) for u in us)), len(rows)


def _find_col(pred, col: str) -> int | None:
    for r in pred[:4]:
        for j, c in enumerate(r):
            if ncell(c).lower() == col.lower():
                return j
    for r in pred[:4]:
        for j, c in enumerate(r):
            if col.lower() in ncell(c).lower():
                return j
    return None


def table_field(tf: dict, blocks: list[dict]) -> bool:
    for b in blocks:
        if not _is_table(b):
            continue
        j = _find_col(b["rows"], tf["col"])
        if j is None:
            continue
        for r in b["rows"]:
            label = next((ncell(c) for c in r if ncell(c)), "")
            if label.lower().startswith(tf["row"].lower()) and j < len(r) and \
                    ncell(r[j]) == tf["value"]:
                return True
    return False


def headings_score(gt_heads: list[str], blocks: list[dict]) -> dict:
    pred = [norm(b["text"]).lower() for b in blocks if b["kind"] == "heading"]
    hit = 0
    for h in gt_heads:
        h = norm(h).lower()
        if any(h == p or (len(p) >= 3 and (h in p or p in h)) for p in pred):
            hit += 1
    return {"gt": len(gt_heads), "pred": len(pred), "matched": hit,
            "recall": round(hit / len(gt_heads), 4) if gt_heads else None}


def score_doc(gt: dict, blocks: list[dict]) -> dict:
    hyp, ref = doc_text(blocks), norm(gt["text"])
    res = {"cer": round(cer(ref, hyp), 4) if hyp else 1.0,
           "chars_ref": len(ref), "chars_hyp": len(hyp)}
    rt, ht = Counter(ref.lower().split()), Counter(hyp.lower().split())
    common = sum((rt & ht).values())
    pr, rc = common / max(1, sum(ht.values())), common / max(1, sum(rt.values()))
    res["token_f1"] = round(2 * pr * rc / (pr + rc), 4) if common else 0.0
    low = hyp.lower()
    kf = {k: any(norm(v).lower() in low for v in vals) for k, vals in gt["key_fields"].items()}
    res["key_fields"] = kf
    res["key_field_recall"] = round(sum(kf.values()) / len(kf), 4) if kf else None
    tabs, us, ri_ok, ri_n = {}, units(blocks), 0, 0
    for t in gt["tables"]:
        tabs[t["name"]] = table_score(t["grid"], blocks)
        ok, n = row_integrity(t["grid"], us)
        tabs[t["name"]]["row_integrity"] = round(ok / n, 4) if n else None
        ri_ok, ri_n = ri_ok + ok, ri_n + n
    res["tables"] = tabs
    total = sum(v["cells_total"] for v in tabs.values())
    res["cells_total"], res["cells_matched"] = total, sum(v["cells_matched"]
                                                          for v in tabs.values())
    res["table_cell_accuracy"] = round(res["cells_matched"] / total, 4) if total else None
    res["rows_total"], res["rows_intact"] = ri_n, ri_ok
    res["row_integrity"] = round(ri_ok / ri_n, 4) if ri_n else None
    tf = {t["field"]: table_field(t, blocks) for t in gt["table_fields"]}
    res["table_fields"] = tf
    res["table_field_accuracy"] = round(sum(tf.values()) / len(tf), 4) if tf else None
    res["headings"] = headings_score(gt["headings"], blocks)
    return res


# ------------------------------------------------------------------ running
def block_dicts(parsed) -> list[dict]:
    return [{"kind": b.kind, "text": b.text, "page": b.page, "rows": b.rows, "level": b.level}
            for b in parsed.blocks]


def evaluate_parser(pdf_parser: str, scan_vlm: str = "off", gt: dict | None = None,
                    fixture_dir=FIXTURE_DIR) -> dict:
    """Parse and score every ground-truth document with this PDF parser. Returns
    {"documents": {filename: metrics}, "totals": {...}}."""
    from aura.ingest.parsers import limits_from_settings, parse
    gt = gt or load_ground_truth()[0]
    limits = replace(limits_from_settings(), pdf_parser=pdf_parser, scan_vlm=scan_vlm)
    docs = {}
    for name, truth in gt["documents"].items():
        content = (fixture_dir / name).read_bytes()
        clock = time.perf_counter()
        error, blocks, warnings = None, [], []
        try:
            parsed = parse(content, name, limits=limits)
            blocks, warnings = block_dicts(parsed), list(parsed.warnings)
        except Exception as exc:  # a document that fails to parse scores zero, not a crash
            error = f"{type(exc).__name__}: {exc}"
        seconds = round(time.perf_counter() - clock, 2)
        metrics = score_doc(truth, blocks)
        metrics.update({"seconds": seconds, "kind": truth["kind"], "pages": truth["pages"],
                        "warnings": warnings, "error": error})
        docs[name] = metrics
    return {"documents": docs, "totals": totals(docs)}


def _ratio(num: float, den: float) -> float | None:
    return round(num / den, 4) if den else None


def _mean(values: list) -> float | None:
    values = [v for v in values if v is not None]
    return round(sum(values) / len(values), 4) if values else None


def totals(docs: dict) -> dict:
    d = docs.values()
    kf = [ok for m in d for ok in m["key_fields"].values()]
    tf = [ok for m in d for ok in m["table_fields"].values()]
    heads = [m["headings"] for m in d]
    fin = docs.get(FINANCIAL_DOC)
    out = {
        "table_cell_accuracy": _ratio(sum(m["cells_matched"] for m in d),
                                      sum(m["cells_total"] for m in d)),
        "financial_table_cell_accuracy": fin["table_cell_accuracy"] if fin else None,
        "row_integrity": _ratio(sum(m["rows_intact"] for m in d),
                                sum(m["rows_total"] for m in d)),
        "table_field_accuracy": _ratio(sum(tf), len(tf)), "table_fields_n": len(tf),
        "key_field_recall": _ratio(sum(kf), len(kf)), "key_fields_n": len(kf),
        "heading_recall": _ratio(sum(h["matched"] for h in heads),
                                 sum(h["gt"] for h in heads)),
        "cer_digital_pdf": _mean([m["cer"] for m in d if m["kind"] == "pdf_digital"]),
        "cer_scanned_pdf": _mean([m["cer"] for m in d if m["kind"] == "pdf_scanned"]),
        "seconds": round(sum(m["seconds"] for m in d), 2),
        "errors": sum(1 for m in d if m["error"]),
    }
    out["score"] = round(sum(out[k] or 0.0 for k in ("table_cell_accuracy",
                                                    "table_field_accuracy",
                                                    "key_field_recall")) / 3, 4)
    return out


def _pct(v) -> str:
    return "-" if v is None else f"{v:.0%}"


def report(pdf_parser: str, result: dict) -> str:
    lines = [f"parser={pdf_parser}",
             (f"  {'document':<40} {'CER':>6} {'cells':>6} {'rows':>6} {'r/c':>7} "
             f"{'keys':>7} {'heads':>6} {'secs':>6}")]
    for name, m in result["documents"].items():
        tf = m["table_fields"]
        kf = m["key_fields"]
        lines.append(
            f"  {name:<40} {m['cer']:>6.3f} {_pct(m['table_cell_accuracy']):>6} "
            f"{_pct(m['row_integrity']):>6} "
            f"{(f'{sum(tf.values())}/{len(tf)}' if tf else '-'):>7} "
            f"{(f'{sum(kf.values())}/{len(kf)}' if kf else '-'):>7} "
            f"{_pct(m['headings']['recall']):>6} {m['seconds']:>6.1f}"
            + (f"  ERROR {m['error']}" if m["error"] else ""))
    t = result["totals"]
    lines.append(
        f"  TOTAL {pdf_parser}: table cells {_pct(t['table_cell_accuracy'])} (financial "
        f"{_pct(t['financial_table_cell_accuracy'])})  row integrity "
        f"{_pct(t['row_integrity'])}  row/col fields {_pct(t['table_field_accuracy'])} "
        f"of {t['table_fields_n']}  key fields {_pct(t['key_field_recall'])} of "
        f"{t['key_fields_n']}  headings {_pct(t['heading_recall'])}  CER digital "
        f"{t['cer_digital_pdf']:.3f} scanned {t['cer_scanned_pdf']:.3f}  "
        f"{t['seconds']:.1f}s  score {t['score']:.3f}")
    return "\n".join(lines)


def to_eval_run(pdf_parser: str, scan_vlm: str, result: dict, digest: str, threshold: float,
                started, created_by: str = "cli"):
    """The EvalRun to store: one case per document, scored by its table-cell accuracy (or key-
    field recall for a document without tables)."""
    from aura.core.clock import utcnow
    from aura.core.domain.harness import EvalCaseResult, EvalRun
    cases = []
    for name, m in result["documents"].items():
        score = m["table_cell_accuracy"]
        if score is None:
            score = m["key_field_recall"] or 0.0
        cases.append(EvalCaseResult(
            id=None, eval_run_id=None, case_id=name[:64], passed=score >= threshold,
            score=float(score), confidence=None, expected={"kind": m["kind"]},
            actual={"chars": m["chars_hyp"], "warnings": m["warnings"]},
            detail={k: v for k, v in m.items() if k not in ("warnings",)},
            latency_ms=int(m["seconds"] * 1000), error=m["error"]))
    t = result["totals"]
    metrics = {"primary": "score", **t, "pdf_parser": pdf_parser, "scan_vlm": scan_vlm,
               "total_latency_ms": int(t["seconds"] * 1000)}
    return EvalRun(id=None, capability="parsing", orchestrator=pdf_parser[:16],
                   model_id=f"{pdf_parser}/vlm-{scan_vlm}", golden_sha256=digest,
                   n_cases=len(cases), score=t["score"], threshold=threshold,
                   passed=t["score"] >= threshold, metrics=metrics, started_at=started,
                   completed_at=utcnow(), created_by=created_by, cases=cases)
