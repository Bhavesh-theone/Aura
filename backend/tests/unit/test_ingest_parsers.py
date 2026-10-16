"""Parsers per format, over the generated fixture pack (tests/fixtures/ingest), including the
OCR path on the image-only PDF page, format detection and the typed errors."""
import io
import zipfile
from pathlib import Path

import pytest

from aura.core.domain.ingest import CorruptDocument, DocumentTooLarge, UnsupportedFormat
from aura.ingest.parsers import (FormatRegistryParser, ParserLimits, check_upload, detect,
                                 html_to_text, ocr_available, parse)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "ingest"
LIMITS = ParserLimits()


def _load(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _text(parsed) -> str:
    return parsed.text


@pytest.mark.skipif(not ocr_available(), reason="rapidocr_onnxruntime is not installed")
def test_pdf_per_page_text_headings_and_ocr_of_the_scanned_page():
    parsed = parse(_load("nilgiri_information_memorandum.pdf"),
                   "nilgiri_information_memorandum.pdf", limits=LIMITS)
    assert parsed.page_count == 3 and parsed.ocr_used
    assert "page 3: text recognised by OCR" in parsed.warnings
    pages = {b.page for b in parsed.blocks}
    assert pages == {1, 2, 3}
    headings = [b.text for b in parsed.blocks if b.kind == "heading"]
    assert "Company overview" in headings and "Financial highlights" in headings
    ocr_text = " ".join(b.text for b in parsed.blocks if b.page == 3)
    assert "show cause notice" in ocr_text.lower() and "4.2 crore" in ocr_text


def test_pdf_without_ocr_warns_about_the_page_with_no_text_layer():
    parsed = parse(_load("nilgiri_information_memorandum.pdf"), "im.pdf",
                   limits=ParserLimits(ocr_enabled=False))
    assert not parsed.ocr_used
    assert "page 3: no text layer (OCR is off)" in parsed.warnings
    assert all(b.page in (1, 2) for b in parsed.blocks)


def test_pdf_ocr_page_limit_is_respected():
    parsed = parse(_load("nilgiri_information_memorandum.pdf"), "im.pdf",
                   limits=ParserLimits(ocr_max_pages=0))
    assert any("OCR limit" in w for w in parsed.warnings) and not parsed.ocr_used


def test_pdf_over_the_page_limit_is_too_large():
    with pytest.raises(DocumentTooLarge):
        parse(_load("nilgiri_information_memorandum.pdf"), "im.pdf",
              limits=ParserLimits(max_pages=2))


def test_docx_keeps_headings_paragraphs_and_tables_in_order():
    parsed = parse(_load("nilgiri_spa_draft.docx"), "spa.docx", limits=LIMITS)
    kinds = [b.kind for b in parsed.blocks]
    assert kinds[0] == "heading" and "table" in kinds
    table = next(b for b in parsed.blocks if b.kind == "table")
    assert table.rows[0] == ["Tranche", "Timing", "Amount (INR crore)"]
    assert kinds.index("table") == [b.text for b in parsed.blocks].index(
        "2. Purchase price") + 2  # heading, paragraph, then its table
    assert "CCI approval" in _text(parsed)


def test_xlsx_each_sheet_is_a_table_with_its_header_and_empty_sheets_are_reported():
    parsed = parse(_load("nilgiri_financial_model.xlsx"), "model.xlsx", limits=LIMITS)
    headings = [b.text for b in parsed.blocks if b.kind == "heading"]
    assert headings == ["Sheet: P&L", "Sheet: Debt schedule", "Sheet: Cap table"]
    debt = [b for b in parsed.blocks if b.kind == "table"][1]
    assert debt.rows[0][0] == "Lender" and debt.rows[1][:3] == ["State Bank of India",
                                                                "Term loan", "85"]
    assert "sheet 'Notes' is empty" in parsed.warnings


def test_csv_is_one_table():
    parsed = parse(_load("nilgiri_dd_tracker.csv"), "tracker.csv", limits=LIMITS)
    assert [b.kind for b in parsed.blocks] == ["table"]
    assert parsed.blocks[0].rows[0] == ["Item", "Workstream", "Status", "Owner"]
    assert len(parsed.blocks[0].rows) == 5


def test_pptx_slides_titles_tables_and_speaker_notes_with_slide_numbers():
    parsed = parse(_load("nilgiri_management_presentation.pptx"), "mp.pptx", limits=LIMITS)
    assert parsed.page_count == 3
    assert [b.text for b in parsed.blocks if b.kind == "heading"][1] == \
        "Slide 2: Customers and channels"
    table = next(b for b in parsed.blocks if b.kind == "table")
    assert table.page == 2 and table.rows[0] == ["Channel", "FY25 share"]
    notes = [b for b in parsed.blocks if b.text.startswith("Speaker notes:")]
    assert {b.page for b in notes} == {1, 3}


def test_eml_headers_body_and_attachments_parsed_recursively():
    parsed = parse(_load("nilgiri_fdd_red_flags.eml"), "fdd.eml", limits=LIMITS)
    text = _text(parsed)
    assert parsed.blocks[0].kind == "heading" and "FDD red flags" in parsed.blocks[0].text
    assert "From: Meera Iyer" in text and "Kaveri Logistics LLP" in text
    assert "Attachments: dd_tracker.csv" in text
    assert any(b.kind == "table" and b.rows[0][0] == "Item" for b in parsed.blocks)
    assert parsed.metadata["attachments"] == 1


def test_eml_html_only_body_is_converted_to_text():
    raw = (b"From: a@example.com\r\nSubject: Hi\r\nMIME-Version: 1.0\r\n"
           b"Content-Type: text/html; charset=utf-8\r\n\r\n"
           b"<html><head><style>p{}</style></head><body><p>Escrow of <b>10%</b></p>"
           b"<table><tr><td>A</td><td>B</td></tr></table><script>x()</script></body></html>")
    parsed = parse(raw, "mail.eml", limits=LIMITS)
    text = _text(parsed)
    assert "Escrow of 10%" in text and "x()" not in text and "p{}" not in text


def test_markdown_headings_and_plain_text_paragraphs():
    parsed = parse(_load("nilgiri_board_minutes.md"), "minutes.md", limits=LIMITS)
    assert [b.text for b in parsed.blocks if b.kind == "heading"][:2] == \
        ["Minutes of the meeting of the Board of Directors", "Present"]
    txt = parse(b"First para.\n\nSecond para.", "notes.txt", limits=LIMITS)
    assert [b.text for b in txt.blocks] == ["First para.", "Second para."]


def test_a_pdf_named_file_that_is_plain_text_is_read_as_text_with_a_warning():
    parsed = parse(b"Board resolution approving the term sheet.", "minutes.pdf",
                   limits=LIMITS)
    assert parsed.text == "Board resolution approving the term sheet."
    assert parsed.warnings == ["the content is plain text, not PDF; read as text"]


@pytest.mark.parametrize("content,name,error", [
    (b"\x00\x01\x02binary", "x.pdf", CorruptDocument),
    (b"%PDF-1.4 broken", "x.pdf", CorruptDocument),
    (b"PK\x03\x04 not a zip", "x.docx", CorruptDocument),
    (b"", "x.txt", CorruptDocument),
    (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 600, "x.msg", CorruptDocument),
    (b"hello", "x.exe", UnsupportedFormat),
    (b"\x00\x01\x02", "noext", UnsupportedFormat),
])
def test_unreadable_files_raise_typed_errors_never_bare_exceptions(content, name, error):
    with pytest.raises(error):
        parse(content, name, limits=LIMITS)


def test_a_docx_with_the_wrong_insides_is_corrupt_not_a_crash():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", "<not really/>")
    with pytest.raises(CorruptDocument):
        parse(buf.getvalue(), "broken.docx", limits=LIMITS)


def test_detection_uses_magic_bytes_when_there_is_no_extension():
    assert detect(_load("nilgiri_spa_draft.docx"), "upload")[0] == "docx"
    assert detect(_load("nilgiri_financial_model.xlsx"), "upload")[0] == "xlsx"
    assert detect(_load("nilgiri_management_presentation.pptx"), "upload")[0] == "pptx"
    assert detect(_load("nilgiri_fdd_red_flags.eml"), "upload")[0] == "eml"
    assert detect(_load("nilgiri_information_memorandum.pdf"), "upload")[0] == "pdf"


def test_check_upload_refuses_unsupported_types_and_oversized_files():
    assert check_upload("a.PDF", b"%PDF-", LIMITS) == "pdf"
    with pytest.raises(UnsupportedFormat):
        check_upload("a.exe", b"MZ", LIMITS)
    with pytest.raises(DocumentTooLarge):
        check_upload("a.txt", b"x" * (1024 * 1024 + 1), ParserLimits(max_upload_mb=1))
    with pytest.raises(DocumentTooLarge):
        parse(b"x" * (1024 * 1024 + 1), "a.txt", limits=ParserLimits(max_upload_mb=1))


def test_html_to_text_survives_broken_markup():
    assert "hello" in html_to_text("<p>hello<div")


def test_registry_parser_is_the_port():
    from aura.core.ports.ingest import DocumentParser
    parser = FormatRegistryParser(LIMITS)
    assert isinstance(parser, DocumentParser)
    assert parser.parse(b"plain", "a.txt").text == "plain"
