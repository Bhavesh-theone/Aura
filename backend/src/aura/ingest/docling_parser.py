"""PDF parsing with Docling (layout model, TableFormer table grids, RapidOCR), the default PDF
path when the optional dependency and its models are installed (RUNNING.md, "PDF parsing").

Why: on the bake-off corpus (docs/research/parser-bakeoff.md) Docling was the only parser that
turned audited statements into correct cell grids (100% of cells, merged headers, bracketed
negatives), found 12/12 headings against PyMuPDF's 1/12, and cut the character error rate on
scans from 0.30 to 0.04. It costs about 4-5 s a page on CPU, against 5 ms for PyMuPDF, so it
runs behind a page cap and a timeout, and anything it cannot do falls back to PyMuPDF.

- One DocumentConverter per process, built on first use and shared under a lock (Docling's
  pipeline is not safe to call from two threads at once, and building it takes ~10 s).
- Models come from AURA_DOCLING_ARTIFACTS (backend/data/docling-models); Hugging Face is
  forced offline, so a missing model fails fast instead of downloading.
- Docling items map to Aura blocks: title / section header -> heading (with level), table ->
  table (its full cell grid, header rows counted, a merged cell's text in the first cell of
  its span only), everything else with text -> text; each with its page number.
"""
import io
import logging
import os
import threading
from pathlib import Path

from aura.core.domain.ingest import Block, ParsedDocument

logger = logging.getLogger(__name__)

# Model folders Docling needs under the artifacts path (layout, TableFormer, RapidOCR).
REQUIRED_MODELS = ("docling-project--docling-layout-heron", "docling-project--docling-models",
                   "RapidOcr")
MAX_HEADER_ROWS = 3


class DoclingUnavailable(RuntimeError):
    """The optional dependency or its models are missing."""


def docling_installed() -> bool:
    try:
        import importlib.util
        return importlib.util.find_spec("docling") is not None
    except Exception:
        return False


def models_present(artifacts: str | os.PathLike | None) -> bool:
    if not artifacts:
        return False
    root = Path(artifacts)
    return all((root / name).is_dir() and any((root / name).iterdir())
               for name in REQUIRED_MODELS)


def docling_available(artifacts: str | os.PathLike | None) -> bool:
    return docling_installed() and models_present(artifacts)


def unavailable_reason(artifacts: str | os.PathLike | None) -> str:
    if not docling_installed():
        return "Docling is not installed (uv sync --extra docling)"
    missing = [n for n in REQUIRED_MODELS if not (Path(artifacts or ".") / n).is_dir()]
    return f"Docling models missing in {artifacts} ({', '.join(missing) or 'empty folder'})"


# ------------------------------------------------------------------ the converter

class _Converter:
    _lock = threading.Lock()
    _converters: dict[tuple, object] = {}

    @classmethod
    def convert(cls, content: bytes, filename: str, artifacts: str, timeout_s: float):
        with cls._lock:
            key = (str(artifacts), float(timeout_s))
            conv = cls._converters.get(key)
            if conv is None:
                conv = cls._build(artifacts, timeout_s)
                cls._converters = {key: conv}  # one live converter: settings rarely change
            from docling.datamodel.base_models import DocumentStream
            name = filename if filename.lower().endswith(".pdf") else f"{filename}.pdf"
            return conv.convert(DocumentStream(name=name, stream=io.BytesIO(content)),
                                raises_on_error=False)

    @staticmethod
    def _build(artifacts: str, timeout_s: float):
        if not docling_available(artifacts):
            raise DoclingUnavailable(unavailable_reason(artifacts))
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
        for noisy in ("RapidOCR", "docling", "docling_ibm_models"):
            logging.getLogger(noisy).setLevel(logging.WARNING)
        from docling.datamodel.accelerator_options import AcceleratorOptions
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import (PdfPipelineOptions, RapidOcrOptions,
                                                        TableFormerMode)
        from docling.document_converter import DocumentConverter, PdfFormatOption
        opts = PdfPipelineOptions(do_ocr=True, do_table_structure=True,
                                  artifacts_path=str(artifacts),
                                  document_timeout=float(timeout_s),
                                  accelerator_options=AcceleratorOptions(device="cpu"))
        opts.table_structure_options.mode = TableFormerMode.ACCURATE
        opts.table_structure_options.do_cell_matching = True
        opts.ocr_options = RapidOcrOptions()
        return DocumentConverter(
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)})


def warm_up(artifacts: str, timeout_s: float = 600.0) -> None:
    """Build the converter now (the first document otherwise pays ~10 s)."""
    with _Converter._lock:
        key = (str(artifacts), float(timeout_s))
        if key not in _Converter._converters:
            _Converter._converters = {key: _Converter._build(artifacts, timeout_s)}


# ------------------------------------------------------------------ mapping

def _clean(text: str | None) -> str:
    return " ".join((text or "").replace("\xa0", " ").split())


def table_grid(table_data) -> tuple[list[list[str]], int, list[str]]:
    """(rows, header_rows, columns) from Docling's TableData.

    Docling repeats a spanning cell in every grid position it covers. In `rows` Aura keeps its
    text in the first position of the span only (as a spreadsheet does), so a merged header
    reads once and the columns stay aligned. Header rows are the leading rows whose cells are
    all column headers. `columns` flattens a multi-row header to one name per column: a
    merged cell names every column it spans, and each column's parts join top to bottom
    ('Year ended 31 March' over 'FY24' -> 'Year ended 31 March FY24'). Empty columns go."""
    grid = getattr(table_data, "grid", None) or []
    rows: list[list[str]] = []
    spread: list[list[str]] = []  # column-span text repeated, row-span text in its first row
    header_flags: list[bool] = []
    for r, row in enumerate(grid):
        cells, wide, flags = [], [], []
        for c, cell in enumerate(row):
            start_r = getattr(cell, "start_row_offset_idx", r)
            start_c = getattr(cell, "start_col_offset_idx", c)
            text = _clean(getattr(cell, "text", ""))
            cells.append(text if start_r == r and start_c == c else "")
            wide.append(text if start_r == r else "")
            if text:
                flags.append(bool(getattr(cell, "column_header", False)))
        rows.append(cells)
        spread.append(wide)
        header_flags.append(bool(flags) and all(flags))
    width = max((len(r) for r in rows), default=0)
    keep_cols = [j for j in range(width) if any(j < len(r) and r[j] for r in rows)]
    keep_rows = [i for i, r in enumerate(rows) if any(r)]
    header = 0
    for i in keep_rows:
        if not header_flags[i] or header >= MAX_HEADER_ROWS:
            break
        header += 1
    rows = [[rows[i][j] if j < len(rows[i]) else "" for j in keep_cols] for i in keep_rows]
    spread = [[spread[i][j] if j < len(spread[i]) else "" for j in keep_cols]
              for i in keep_rows]
    # A table keeps at least one body row; a one-row table has one header row.
    header = max(1, min(header, len(rows) - 1)) if len(rows) > 1 else 1
    columns = []
    for j in range(len(keep_cols)):
        parts: list[str] = []
        for row in spread[:header]:
            if row[j] and (not parts or parts[-1] != row[j]):
                parts.append(row[j])
        columns.append(" ".join(parts))
    return rows, header, columns


def _label(item) -> str:
    label = getattr(item, "label", "")
    return str(getattr(label, "value", label) or "")


def map_document(doc) -> list[Block]:
    """Docling's DoclingDocument -> Aura blocks, in reading order. Duck-typed on the item
    labels ('title', 'section_header', 'table', ...), so it needs no Docling import."""
    blocks: list[Block] = []
    for item, _depth in doc.iterate_items():
        prov = getattr(item, "prov", None) or []
        page = prov[0].page_no if prov else None
        label = _label(item)
        if label in ("table", "document_index") and getattr(item, "data", None) is not None:
            rows, header, columns = table_grid(item.data)
            if not rows:
                continue
            meta = {"header_rows": header, "source": "docling"}
            if header > 1:
                meta["columns"] = columns
            caption = _clean(item.caption_text(doc)) if hasattr(item, "caption_text") else ""
            if caption:
                meta["caption"] = caption
            blocks.append(Block("table", "\n".join(" | ".join(r) for r in rows), page,
                                rows=rows, meta=meta))
            continue
        text = getattr(item, "text", None)
        if not text or not text.strip():
            continue
        if label in ("title", "section_header"):
            level = 1 if label == "title" else min(6, int(getattr(item, "level", 1) or 1) + 1)
            blocks.append(Block("heading", _clean(text), page, level=level))
        else:
            blocks.append(Block("text", text.strip(), page))
    return blocks


def parse_with_docling(content: bytes, filename: str, artifacts: str, timeout_s: float,
                       page_count: int) -> ParsedDocument:
    """Docling's reading of a PDF. Raises when Docling is unavailable, fails, or does not
    finish every page within the timeout (the caller falls back to PyMuPDF)."""
    from docling.datamodel.base_models import ConversionStatus
    result = _Converter.convert(content, filename, artifacts, timeout_s)
    status = getattr(result, "status", None)
    if status != ConversionStatus.SUCCESS:
        errors = "; ".join(str(getattr(e, "error_message", e))
                           for e in (getattr(result, "errors", None) or [])[:3])
        raise RuntimeError(f"Docling {getattr(status, 'value', status)}"
                           f"{': ' + errors if errors else ''}"
                           f"{' (timeout?)' if status == ConversionStatus.PARTIAL_SUCCESS else ''}")
    doc = result.document
    blocks = map_document(doc)
    pages = len(doc.pages) if getattr(doc, "pages", None) else page_count
    return ParsedDocument(blocks=blocks, page_count=pages or page_count,
                          metadata={"parser": "docling"})


class DoclingPdfParser:
    """The DocumentParser port for PDFs read by Docling, with the PyMuPDF fallback chain and
    the vision-model pass of aura.ingest.parsers (it is FormatRegistryParser forced to
    pdf_parser='docling'; other formats go to their usual parsers)."""

    def __init__(self, limits=None, vlm=None):
        from dataclasses import replace

        from aura.ingest.parsers import FormatRegistryParser, limits_from_settings
        limits = replace(limits or limits_from_settings(), pdf_parser="docling")
        self._inner = FormatRegistryParser(limits, vlm=vlm)

    def parse(self, content: bytes, filename: str, mime: str | None = None) -> ParsedDocument:
        return self._inner.parse(content, filename, mime)
