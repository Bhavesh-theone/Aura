"""Second reading of scanned PDF pages by a local vision model (AURA_SCAN_VLM).

OCR (RapidOCR, alone or inside Docling) loses dense lines and handwritten fields on scans; the
bake-off (docs/research/parser-bakeoff.md) found qwen3.5:4b read both test scans perfectly, at
about 50 s a page. So it is a capped second pass, never the only reading:

- which pages: image-only pages (no text layer) whose OCR text is thin ('fallback'), plus every
  image-only page of a scan whose file name says it is a KYC paper or a board resolution; or
  every image-only page ('always'); at most vlm_max_pages per document;
- each page is rendered at 150 dpi and transcribed to Markdown at temperature 0 with thinking
  off (qwen3.5 otherwise spends its output budget reasoning);
- a number in the transcription counts only if OCR saw it too: otherwise the page's blocks are
  marked needs_review and a warning names the numbers;
- each call takes a slot of the process-wide model-call semaphore (max_concurrent_llm_calls)
  and leaves an embed_run row (kind 'vlm_page'), not an agent_run row: it is ingestion, not
  agent work, so it does not count against the daily model budget;
- a failure (Ollama down, no free slot, timeout) keeps the OCR reading, with a warning.
"""
import base64
import logging
import re
import time
from dataclasses import dataclass

from aura.core.clock import utcnow
from aura.core.domain.ingest import Block, EmbedRun

logger = logging.getLogger(__name__)

PROMPT = ("Transcribe this scanned document page exactly. Output GitHub Markdown: '#' for the "
          "main title, '##' for section headings, Markdown tables (with a header row) for every "
          "table, and plain lines for everything else, including handwritten entries. Copy "
          "every number, code and name character for character. Ignore stamps and signatures. "
          "Output only the transcription.")
RENDER_DPI = 150
# An image-only page whose OCR found fewer characters than this is "thin" (fallback mode).
THIN_OCR_CHARS = 200
# Scans whose name says they hold identity or signed fields are read even when OCR is not thin.
FLAGGED_NAME = re.compile(r"kyc|board[\s_-]*resolution|resolution|aadhaa?r|\bpan\b|passport|"
                          r"signed|signature|specimen", re.IGNORECASE)


@dataclass
class VlmReading:
    markdown: str
    latency_ms: int
    model: str


class OllamaVlm:
    """Ollama /api/chat with an image. One call at a time per model slot."""

    def __init__(self, base_url: str, model: str, timeout: float = 300.0,
                 slot_timeout: float | None = None):
        self.base_url, self.model, self.timeout = base_url.rstrip("/"), model, timeout
        self.slot_timeout = timeout if slot_timeout is None else slot_timeout

    def read(self, png: bytes) -> VlmReading:
        import httpx

        from aura.agents.llm.recording import llm_slot
        slot = llm_slot(self.slot_timeout)
        try:
            started = time.perf_counter()
            r = httpx.post(f"{self.base_url}/api/chat", timeout=self.timeout, json={
                "model": self.model, "stream": False, "think": False,
                "options": {"temperature": 0, "num_ctx": 8192, "num_predict": 2500},
                "messages": [{"role": "user", "content": PROMPT,
                              "images": [base64.b64encode(png).decode()]}]})
            r.raise_for_status()
            content = (r.json().get("message") or {}).get("content") or ""
            return VlmReading(content, int((time.perf_counter() - started) * 1000), self.model)
        finally:
            slot.release()


def vlm_from_settings():
    from aura.config import get_settings
    s = get_settings()
    return OllamaVlm(s.ollama_base_url, s.vlm_model, s.vlm_timeout_s)


# ------------------------------------------------------------------ markdown -> blocks

def _cells(line: str) -> list[str]:
    return [c.strip().replace("**", "") for c in line.strip().strip("|").split("|")]


def markdown_blocks(md: str, page: int | None) -> list[Block]:
    """The vision model's Markdown as Aura blocks: '#' headings, '|' tables, paragraphs."""
    blocks: list[Block] = []
    para: list[str] = []
    table: list[str] = []

    def flush():
        if para:
            blocks.append(Block("text", "\n".join(para), page, meta={"source": "vlm"}))
            para.clear()
        if table:
            rows = [_cells(r) for r in table]
            rows = [r for r in rows if not all(set(c) <= set("-: ") for c in r)]
            if rows:
                blocks.append(Block("table", "\n".join(" | ".join(r) for r in rows), page,
                                    rows=rows, meta={"source": "vlm"}))
            table.clear()

    for line in (md or "").splitlines():
        s = line.strip()
        if s.startswith("```"):
            continue
        if s.startswith("|"):
            if para:
                blocks.append(Block("text", "\n".join(para), page, meta={"source": "vlm"}))
                para.clear()
            table.append(s)
            continue
        if table:
            flush()
        if not s:
            flush()
        elif s.startswith("#"):
            flush()
            level = len(s) - len(s.lstrip("#"))
            title = s.lstrip("#").strip().replace("**", "")
            if title:
                blocks.append(Block("heading", title, page, level=min(level, 6),
                                    meta={"source": "vlm"}))
        else:
            para.append(s.replace("**", ""))
    flush()
    return blocks


# ------------------------------------------------------------------ corroboration

_NUMBER = re.compile(r"\d[\d,./:-]*\d|\d")


def _norm_number(token: str) -> str:
    return re.sub(r"[^\d.]", "", token).strip(".")


def numbers(text: str) -> list[str]:
    """Numeric tokens worth checking (two or more digits), normalised to digits and dots."""
    out = []
    for m in _NUMBER.finditer(text or ""):
        n = _norm_number(m.group(0))
        if sum(ch.isdigit() for ch in n) >= 2:
            out.append(n)
    return out


def uncorroborated(vlm_text: str, ocr_text: str) -> list[str]:
    """Numbers in the vision model's reading that the OCR text does not contain (separators
    ignored: '1,20,000' and '120000' agree)."""
    ocr_set = {n.replace(".", "") for n in numbers(ocr_text)}
    missing = []
    for n in numbers(vlm_text):
        if n.replace(".", "") in ocr_set:
            continue
        if n not in missing:
            missing.append(n)
    return missing


# ------------------------------------------------------------------ the pass

def pages_to_read(image_pages: list[int], ocr_chars: dict[int, int], mode: str,
                  filename: str, max_pages: int) -> list[int]:
    if mode == "off" or max_pages <= 0:
        return []
    flagged = bool(FLAGGED_NAME.search(filename or ""))
    chosen = [p for p in image_pages
              if mode == "always" or flagged or ocr_chars.get(p, 0) < THIN_OCR_CHARS]
    return chosen[:max_pages]


def apply_vlm(parsed, page_png, image_pages: list[int], mode: str, filename: str,
              max_pages: int, vlm) -> None:
    """Replace the OCR reading of the chosen image-only pages with the vision model's, in
    place. `page_png(page_number) -> bytes` renders a page."""
    ocr_text = {}
    for b in parsed.blocks:
        if b.page is not None:
            ocr_text[b.page] = ocr_text.get(b.page, "") + "\n" + _block_text(b)
    chosen = pages_to_read(image_pages, {p: len(t.strip()) for p, t in ocr_text.items()},
                           mode, filename, max_pages)
    skipped = [p for p in image_pages if p not in chosen]
    if mode != "off" and len(image_pages) > max_pages and skipped:
        parsed.warnings.append(f"vision model: page limit of {max_pages} reached; "
                               f"{len(skipped)} scanned page(s) kept as OCR read them")
    for page in chosen:
        started, clock = utcnow(), time.perf_counter()
        error, reading = None, None
        try:
            reading = vlm.read(page_png(page))
            if not reading.markdown.strip():
                raise RuntimeError("empty transcription")
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"[:500]
            logger.warning("vision model failed on page %s of %s: %s", page, filename, error)
            parsed.warnings.append(f"page {page}: vision model unavailable ({error[:160]}); "
                                   "kept the OCR text")
        parsed.model_runs.append(EmbedRun(
            id=None, deal_id=None, document_id=None, model=getattr(vlm, "model", "vlm"),
            kind="vlm_page", batch_size=1,
            input_chars=len(reading.markdown) if reading else 0, dimensions=None,
            latency_ms=reading.latency_ms if reading else
            int((time.perf_counter() - clock) * 1000),
            status="error" if error else "ok", error=error, created_at=started))
        if error:
            continue
        new_blocks = markdown_blocks(reading.markdown, page)
        if not new_blocks:
            continue
        missing = uncorroborated(reading.markdown, ocr_text.get(page, ""))
        for b in new_blocks:
            if missing:
                b.meta["needs_review"] = True
                b.meta["uncorroborated"] = missing[:20]
        if missing:
            shown = ", ".join(missing[:8]) + (" ..." if len(missing) > 8 else "")
            parsed.warnings.append(f"page {page}: read by the vision model; {len(missing)} "
                                   f"number(s) not confirmed by OCR ({shown}): needs review")
        else:
            parsed.warnings.append(f"page {page}: read by the vision model (numbers confirmed "
                                   "by OCR)")
        _replace_page(parsed, page, new_blocks)
        parsed.ocr_used = True


def _block_text(b: Block) -> str:
    if b.rows:
        return "\n".join(" ".join(c for c in r if c) for r in b.rows)
    return b.text or ""


def _replace_page(parsed, page: int, new_blocks: list[Block]) -> None:
    blocks = parsed.blocks
    idx = [i for i, b in enumerate(blocks) if b.page == page]
    if idx:
        at = idx[0]
        kept = [b for b in blocks if b.page != page]
        parsed.blocks = kept[:at] + new_blocks + kept[at:]
        return
    at = next((i for i, b in enumerate(blocks) if b.page is not None and b.page > page),
              len(blocks))
    parsed.blocks = blocks[:at] + new_blocks + blocks[at:]
