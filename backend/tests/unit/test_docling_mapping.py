"""Docling output -> Aura blocks, without running Docling: table_grid over fake cells, and
map_document over a cached DoclingDocument (tests/fixtures/parsing/docling_audited_financials.json,
real Docling output on kaveri_audited_financials_fy24.pdf), plus how the chunker carries a
multi-row header."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from aura.core.domain.ingest import Block, ParsedDocument
from aura.core.services.chunking import ChunkingParams, chunk_document
from aura.ingest.docling_parser import table_grid

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "parsing" / \
    "docling_audited_financials.json"


# ------------------------------------------------------------------ table_grid (fake cells)

def _cell(text, r, c, header=False):
    return SimpleNamespace(text=text, start_row_offset_idx=r, start_col_offset_idx=c,
                           column_header=header)


def _grid(*rows):
    return SimpleNamespace(grid=[list(r) for r in rows])


def test_table_grid_merged_column_header_row_span_and_empty_column():
    span = _cell("Year ended 31 March", 0, 2, header=True)   # spans columns 2-3
    part = _cell("Particulars", 0, 0, header=True)          # spans rows 0-1
    note = _cell("Note", 0, 1, header=True)                  # spans rows 0-1
    blank = _cell("", 0, 4)                                 # an empty column (4)
    data = _grid(
        [part, note, span, span, blank],
        [part, note, _cell("FY24", 1, 2, True), _cell("FY23", 1, 3, True), _cell("", 1, 4)],
        [_cell("Revenue", 2, 0), _cell("24", 2, 1), _cell("412.38", 2, 2),
         _cell("356.91", 2, 3), _cell("", 2, 4)],
        [_cell("Exceptional items", 3, 0), _cell("31", 3, 1), _cell("(3.42)", 3, 2),
         _cell("1.15", 3, 3), _cell("", 3, 4)],
    )
    rows, header, columns = table_grid(data)
    assert header == 2
    assert rows[0] == ["Particulars", "Note", "Year ended 31 March", ""]  # span text once
    assert rows[1] == ["", "", "FY24", "FY23"]                            # row span not repeated
    assert rows[3] == ["Exceptional items", "31", "(3.42)", "1.15"]
    assert all(len(r) == 4 for r in rows)                                # empty column dropped
    assert columns == ["Particulars", "Note", "Year ended 31 March FY24",
                       "Year ended 31 March FY23"]


def test_table_grid_single_header_row_and_one_row_table():
    rows, header, columns = table_grid(_grid(
        [_cell("Lender", 0, 0, True), _cell("Amount", 0, 1, True)],
        [_cell("SBI", 1, 0), _cell("120.00", 1, 1)]))
    assert header == 1 and rows == [["Lender", "Amount"], ["SBI", "120.00"]]
    assert columns == ["Lender", "Amount"]

    rows, header, _ = table_grid(_grid([_cell("Only", 0, 0), _cell("row", 0, 1)]))
    assert rows == [["Only", "row"]] and header == 1

    # A table whose every row is flagged as header keeps one body row.
    rows, header, _ = table_grid(_grid([_cell("a", 0, 0, True)], [_cell("b", 1, 0, True)]))
    assert header == 1 and len(rows) == 2

    assert table_grid(SimpleNamespace(grid=[])) == ([], 1, [])


# ------------------------------------------------------------------ map_document (cached JSON)

@pytest.fixture(scope="module")
def mapped():
    docling_core = pytest.importorskip("docling_core")  # noqa: F841
    from docling_core.types.doc import DoclingDocument

    from aura.ingest.docling_parser import map_document
    doc = DoclingDocument.model_validate(json.loads(FIXTURE.read_text(encoding="utf-8")))
    return map_document(doc)


def test_map_document_headings_with_levels(mapped):
    headings = {b.text: b for b in mapped if b.kind == "heading"}
    for title in ("Statement of Profit and Loss for the year ended 31 March 2024",
                  "Balance Sheet as at 31 March 2024"):
        assert title in headings
        assert headings[title].level and 1 <= headings[title].level <= 6
    assert headings["Statement of Profit and Loss for the year ended 31 March 2024"].page == 1
    assert headings["Balance Sheet as at 31 March 2024"].page == 2
    assert {b.page for b in mapped} == {1, 2}


def test_map_document_profit_and_loss_grid(mapped):
    tables = [b for b in mapped if b.kind == "table"]
    pl = next(t for t in tables if any(r and r[0] == "Revenue from operations"
                                       for r in t.rows))
    assert pl.page == 1
    assert pl.meta["header_rows"] == 2 and pl.meta["source"] == "docling"
    assert pl.rows[0] == ["Particulars", "Note", "Year ended 31 March", ""]
    assert pl.rows[1][2:] == ["FY24", "FY23"]
    assert pl.meta["columns"] == ["Particulars", "Note", "Year ended 31 March FY24",
                                  "Year ended 31 March FY23"]
    fy24 = pl.meta["columns"].index("Year ended 31 March FY24")
    exceptional = next(r for r in pl.rows if r[0] == "Exceptional items")
    assert exceptional[fy24] == "(3.42)"
    # the text form is the grid, one row a line
    assert pl.text.splitlines()[0] == "Particulars | Note | Year ended 31 March | "


# ------------------------------------------------------------------ chunking a 2-row header

def test_chunking_repeats_both_header_rows_and_carries_columns():
    columns = ["Particulars", "Note", "Year ended 31 March FY24", "Year ended 31 March FY23"]
    rows = [["Particulars", "Note", "Year ended 31 March", ""], ["", "", "FY24", "FY23"]]
    rows += [[f"Line item number {i} with a long description", str(i), f"{i}.00", f"{i}.50"]
             for i in range(40)]
    table = Block("table", "\n".join(" | ".join(r) for r in rows), 1, rows=rows,
                  meta={"header_rows": 2, "columns": columns, "source": "docling"})
    parsed = ParsedDocument(blocks=[Block("heading", "Statement of Profit and Loss", 1,
                                          level=2), table])
    chunks = chunk_document(parsed, ChunkingParams(target_tokens=100, overlap_tokens=10))
    tables = [c for c in chunks if c.kind == "table"]
    assert len(tables) > 2
    header = "Particulars | Note | Year ended 31 March | \n |  | FY24 | FY23"
    body_rows = 0
    for c in tables:
        assert c.text.startswith("Statement of Profit and Loss\n" + header + "\n")
        assert c.meta["columns"] == columns
        assert c.meta["header"] == header
        assert c.heading == "Statement of Profit and Loss"
        body_rows += c.meta["rows"]
    assert body_rows == 40
