"""PyMuPDF-path layout fixes: heading detection (size ratio, bold standalone lines, headings
sharing a block with their body), OCR line grouping by vertical overlap, and deskew before
OCR. PDFs and page images are built in the test."""
import math
from pathlib import Path

import fitz
import numpy as np
import pytest

from aura.ingest.parsers import (ParserLimits, _is_heading, _join_line, _page_blocks,
                                 estimate_skew, ocr_lines, ocr_lines_text, parse, render_for_ocr)

SCAN = Path(__file__).resolve().parents[1] / "fixtures" / "parsing" / \
    "kaveri_borrowings_schedule_scanned.pdf"
LIMITS = ParserLimits(ocr_enabled=False)
BODY = ("Revenue from operations grew steadily over the period under review, supported by "
        "new customers in the export market and better realisations on core products.")


def _pdf(draw) -> bytes:
    doc = fitz.open()
    draw(doc.new_page())
    return doc.tobytes()


def _body(page, y: float, lines: int = 6, size: float = 9):
    for i in range(lines):
        page.insert_text((72, y + i * 40), BODY[:90], fontname="helv", fontsize=size)


def _blocks(content: bytes):
    return [(b.kind, b.text, b.level) for b in parse(content, "t.pdf", limits=LIMITS).blocks]


# ------------------------------------------------------------------ headings

def test_slightly_larger_bold_heading_over_body_is_a_heading():
    def draw(page):
        page.insert_text((72, 72), "Financial highlights", fontname="hebo", fontsize=10.5)
        _body(page, 120)
    blocks = _blocks(_pdf(draw))
    assert blocks[0] == ("heading", "Financial highlights", 3)  # 10.5 / 9 = 1.17
    assert all(k == "text" for k, _, _ in blocks[1:])


def test_large_heading_gets_level_one():
    def draw(page):
        page.insert_text((72, 72), "Information Memorandum", fontname="helv", fontsize=16)
        _body(page, 120)
    assert _blocks(_pdf(draw))[0] == ("heading", "Information Memorandum", 1)


def test_bold_body_size_standalone_line_is_a_heading():
    def draw(page):
        page.insert_text((72, 72), "Key risks", fontname="hebo", fontsize=9)
        _body(page, 120)
    blocks = _blocks(_pdf(draw))
    assert blocks[0] == ("heading", "Key risks", 3)


def test_bold_cell_in_a_table_row_is_not_a_heading():
    def draw(page):
        for i, (label, value) in enumerate([("Revenue", "412.38"), ("EBITDA", "68.15")]):
            y = 72 + i * 30
            page.insert_text((72, y), label, fontname="hebo", fontsize=9)
            page.insert_text((360, y), value, fontname="hebo", fontsize=9)
        _body(page, 200)
    blocks = _blocks(_pdf(draw))
    assert not any(k == "heading" for k, _, _ in blocks), blocks
    text = " ".join(t for _, t, _ in blocks)
    assert "Revenue" in text and "412.38" in text


def test_is_heading_rules_directly():
    head = ("Key risks", 9.0, True, (72, 60, 120, 72))
    cell = ("Revenue", 9.0, True, (72, 100, 120, 112))
    value = ("412.38", 9.0, False, (360, 100, 400, 112))
    others = [head[3], cell[3], value[3]]
    assert _is_heading(head, 9.0, others)
    assert not _is_heading(cell, 9.0, others)                    # shares its line with a value
    assert not _is_heading(("Revenue grew.", 9.0, True, (72, 200, 150, 212)), 9.0, [])
    assert not _is_heading(("Key risks", 9.0, False, (72, 60, 120, 72)), 9.0, [])  # not bold
    assert not _is_heading(("2023-24", 14.0, True, (72, 60, 120, 72)), 9.0, [])    # no words
    assert not _is_heading(("x" * 130, 14.0, True, (72, 60, 120, 72)), 9.0, [])    # too long
    assert _is_heading(("Overview", 10.1, False, (72, 60, 120, 72)), 9.0, [])     # 1.12x


def test_heading_sharing_a_block_with_its_body_is_split_out():
    found = [[("Working capital", 9.0, True, (72, 60, 160, 72)),
              ("Net working capital days rose to 74 days.", 9.0, False, (72, 73, 300, 85)),
              ("Receivables drove most of it.", 9.0, False, (72, 86, 250, 98))]]
    blocks = _page_blocks(found, 9.0, 2)
    assert [(b.kind, b.text, b.page) for b in blocks] == [
        ("heading", "Working capital", 2),
        ("text", "Net working capital days rose to 74 days.\nReceivables drove most of it.", 2)]
    # a bold line inside a paragraph is emphasis, not a heading
    found = [[("Net working capital days rose.", 9.0, False, (72, 60, 300, 72)),
              ("Important", 9.0, True, (72, 73, 140, 85))]]
    assert [b.kind for b in _page_blocks(found, 9.0, 1)] == ["text"]


def test_heading_in_the_same_pdf_block_as_its_body():
    def draw(page):
        tw = fitz.TextWriter(page.rect)
        bold, regular = fitz.Font("hebo"), fitz.Font("helv")
        tw.append((72, 72), "Working capital", font=bold, fontsize=9)
        tw.append((72, 83), "Net working capital days rose to 74 days in FY24.", font=regular,
                  fontsize=9)
        tw.append((72, 94), "Receivables drove most of the increase.", font=regular,
                  fontsize=9)
        tw.write_text(page)
        _body(page, 200)
    content = _pdf(draw)
    page = fitz.open(stream=content, filetype="pdf")[0]
    first = page.get_text("dict")["blocks"][0]
    assert len(first["lines"]) >= 2  # PyMuPDF put the heading and its body in one block
    blocks = _blocks(content)
    assert blocks[0] == ("heading", "Working capital", 3)
    assert blocks[1][0] == "text" and blocks[1][1].startswith("Net working capital days")


# ------------------------------------------------------------------ OCR line grouping

def _box(x0, y0, x1, y1, text, score=0.95):
    return [[[x0, y0], [x1, y0], [x1, y1], [x0, y1]], text, score]


def test_rotated_table_rows_group_into_lines_left_to_right():
    slope = math.tan(math.radians(1.0))
    cells = [["Lender", "Sanctioned", "Outstanding", "Rate"],
             ["SBI", "60.00", "42.30", "9.10%"]]
    result = []
    for r, row in enumerate(cells):
        for c, text in enumerate(row):
            x0 = 40 + c * 400
            y0 = 100 + r * 50 + x0 * slope
            result.append(_box(x0, y0, x0 + 200, y0 + 30, text))
    result.reverse()  # input order must not matter
    # fixed 12-px buckets of the box centres would scatter each row over several lines
    centres = sorted({int((b[0][0][1] + b[0][2][1]) / 2 // 12) for b in result[:4]})
    assert len(centres) > 1
    lines = ocr_lines(result)
    assert [[b[4] for b in ln] for ln in lines] == cells
    assert ocr_lines_text(result) == "Lender Sanctioned Outstanding Rate\nSBI 60.00 42.30 9.10%"


def test_join_line_spaces_touching_boxes_and_low_scores():
    result = [_box(0, 0, 30, 20, "Rev"), _box(31, 0, 71, 20, "enue"),       # touching: one word
              _box(100, 0, 160, 20, "412.38"), _box(200, 0, 260, 20, "junk", score=0.3)]
    assert ocr_lines_text(result) == "Revenue 412.38"
    lines = ocr_lines(result)
    assert len(lines) == 1 and _join_line(lines[0]) == "Revenue 412.38"
    assert ocr_lines([[None, "x", "bad"], _box(0, 0, 10, 10, "  ", 0.9)]) == []
    assert ocr_lines_text([]) == ""


def test_big_vertical_gap_inserts_a_blank_line():
    result = [_box(0, 0, 100, 20, "Line one"), _box(0, 25, 100, 45, "Line two"),
              _box(0, 120, 100, 140, "New paragraph")]
    assert ocr_lines_text(result) == "Line one\nLine two\n\nNew paragraph"


# ------------------------------------------------------------------ deskew

def _bars(angle: float, height: int = 1000, width: int = 800) -> np.ndarray:
    """White page with dark horizontal text-like bars, rotated so lines fall by `angle`
    degrees to the right (y grows with x)."""
    img = np.full((height, width), 255, dtype=np.uint8)
    slope = math.tan(math.radians(angle))
    xs = np.arange(60, width - 60)
    for y0 in range(80, height - 80, 28):
        for t in range(4):
            ys = np.round(y0 + t + (xs - width / 2) * slope).astype(int)
            ok = (ys >= 0) & (ys < height)
            img[ys[ok], xs[ok]] = 0
    return img


@pytest.mark.parametrize("angle", [1.5, -2.0, 0.8, -1.2])
def test_estimate_skew_finds_the_angle(angle):
    assert abs(estimate_skew(_bars(angle)) - angle) <= 0.2


def test_estimate_skew_straight_and_blank_pages():
    assert abs(estimate_skew(_bars(0.0))) <= 0.05
    assert estimate_skew(np.full((200, 200), 255, dtype=np.uint8)) == 0.0


def _gray(png: bytes) -> np.ndarray:
    pix = fitz.Pixmap(fitz.csGRAY, fitz.Pixmap(png))
    return np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.stride)[
        :, :pix.width]


def test_render_for_ocr_straightens_the_skewed_scan():
    if not SCAN.exists():
        pytest.fail(f"fixture missing: {SCAN}")
    with fitz.open(SCAN) as doc:
        png, angle = render_for_ocr(doc[0])
        assert abs(angle - (-1.2)) <= 0.2
        assert abs(estimate_skew(_gray(png))) <= 0.2
        # a straight page is rendered as is
        straight = fitz.open()
        page = straight.new_page()
        for i in range(20):
            page.insert_text((72, 72 + i * 30), "Straight line of text " * 3, fontsize=11)
        png, angle = render_for_ocr(page)
        assert angle == 0.0 and png.startswith(b"\x89PNG")
