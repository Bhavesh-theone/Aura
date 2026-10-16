"""Real Docling (layout model, TableFormer, RapidOCR) on the scanned borrowings schedule,
through the production parser port. Slow (~30-60 s: the converter is built once, then OCR and
table structure run on CPU) and needs the optional dependency and its models; no database."""
from pathlib import Path

import pytest

from aura.config import get_settings
from aura.ingest.docling_parser import docling_installed, models_present
from aura.ingest.parsers import FormatRegistryParser, ParserLimits

SCAN = Path(__file__).resolve().parents[1] / "fixtures" / "parsing" / \
    "kaveri_borrowings_schedule_scanned.pdf"
ARTIFACTS = get_settings().docling_artifacts

pytestmark = [
    pytest.mark.skipif(not docling_installed(),
                       reason="Docling optional dependency not installed: "
                              "uv sync --extra docling"),
    pytest.mark.skipif(not models_present(ARTIFACTS),
                       reason=f"Docling models missing in {ARTIFACTS} (see RUNNING.md, "
                              "'PDF parsing: Docling')"),
]


def test_docling_reads_the_scanned_borrowings_schedule(monkeypatch):
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")
    parser = FormatRegistryParser(ParserLimits(pdf_parser="docling", docling_artifacts=ARTIFACTS,
                                               scan_vlm="off"))
    parsed = parser.parse(SCAN.read_bytes(), SCAN.name)

    assert parsed.metadata["parser"] == "docling", parsed.warnings
    assert parsed.ocr_used and parsed.page_count == 1
    assert "page(s) 1: text recognised by OCR (Docling)" in parsed.warnings
    assert not any("PyMuPDF instead" in w for w in parsed.warnings)

    headings = [b.text for b in parsed.blocks if b.kind == "heading"]
    assert "Schedule of Borrowings as at 31 March 2024" in headings

    tables = [b for b in parsed.blocks if b.kind == "table"]
    assert len(tables) == 1
    table = tables[0]
    assert table.page == 1 and table.meta["source"] == "docling"
    assert len(table.rows) == 7 and all(len(r) == 6 for r in table.rows)
    assert table.rows[0] == ["Lender", "Facility", "Sanctioned", "Outstanding", "Rate",
                             "Maturity"]
    assert table.meta["header_rows"] == 1
    sbi = next(r for r in table.rows if r[0] == "State Bank of India")
    assert sbi[1:4] == ["Term loan", "60.00", "42.30"]
    assert table.rows[-1][0] == "Total" and "117.75" in table.rows[-1]
