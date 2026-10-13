"""The PDF routing around Docling (missing, failing, over its page cap -> PyMuPDF, with a
warning) and the vision-model pass over scanned pages, with a fake vision model: which pages
it reads, the OCR corroboration of its numbers, failures, lineage rows and needs_review in the
chunks. No Docling models and no Ollama needed."""
import base64
from pathlib import Path

import fitz
import pytest

from aura.core.domain.ingest import Block
from aura.core.services.chunking import chunk_document
from aura.ingest import docling_parser as dl
from aura.ingest import parsers
from aura.ingest import vlm as vlm_mod
from aura.ingest.parsers import FormatRegistryParser, ParserLimits, resolve_pdf_parser
from aura.ingest.vlm import (THIN_OCR_CHARS, OllamaVlm, VlmReading, markdown_blocks, numbers,
                             uncorroborated)

IM = Path(__file__).resolve().parents[1] / "fixtures" / "ingest" / \
    "nilgiri_information_memorandum.pdf"

SHORT_OCR = "Show cause notice\nDemand of INR 4.2 crore under section 74, dated 12 March 2024"
LONG_OCR = SHORT_OCR + "\n" + ("The notice concerns input tax credit availed in FY22. " * 6)
assert len(LONG_OCR) > THIN_OCR_CHARS > len(SHORT_OCR)


class FakeVlm:
    model = "fake-vlm:1b"

    def __init__(self, markdown="# Show cause notice\n\nDemand of INR 4.2 crore dated 12 March "
                 "2024", fail: Exception | None = None):
        self.markdown, self.fail, self.calls = markdown, fail, 0

    def read(self, png: bytes) -> VlmReading:
        self.calls += 1
        assert png.startswith(b"\x89PNG")
        if self.fail:
            raise self.fail
        return VlmReading(self.markdown, 42, self.model)


def _im() -> bytes:
    return IM.read_bytes()


def _parse(content, filename, vlm=None, **limits):
    return FormatRegistryParser(ParserLimits(**limits), vlm=vlm).parse(content, filename)


@pytest.fixture
def ocr_text(monkeypatch):
    """Stub RapidOCR with a fixed reading of the scanned page."""
    def use(text):
        monkeypatch.setattr(parsers._Ocr, "read", lambda png: text)
        monkeypatch.setattr(parsers, "render_for_ocr", lambda page: (b"\x89PNG", 0.0))
    return use


def _blank_pdf(pages: int) -> bytes:
    doc = fitz.open()
    for _ in range(pages):
        page = doc.new_page()
        page.draw_rect(fitz.Rect(72, 72, 300, 200), color=(0, 0, 0), fill=(0.5, 0.5, 0.5))
    return doc.tobytes()


# ------------------------------------------------------------------ Docling fallback chain

def test_docling_models_missing_falls_back_to_pymupdf(tmp_path):
    parsed = _parse(_im(), "im.pdf", pdf_parser="docling", docling_artifacts=str(tmp_path),
                    ocr_enabled=False)
    assert parsed.metadata["parser"] == "pymupdf"
    assert any("read with PyMuPDF instead" in w for w in parsed.warnings)
    assert parsed.warnings[0].endswith("read with PyMuPDF instead")
    assert any(b.kind == "heading" and b.text == "Company overview" for b in parsed.blocks)


def test_docling_failure_falls_back_to_pymupdf(tmp_path, monkeypatch):
    def boom(*args, **kwargs):
        raise ValueError("layout model exploded")
    monkeypatch.setattr(dl, "docling_available", lambda artifacts: True)
    monkeypatch.setattr(dl, "parse_with_docling", boom)
    parsed = _parse(_im(), "im.pdf", pdf_parser="docling", docling_artifacts=str(tmp_path),
                    ocr_enabled=False)
    assert parsed.metadata["parser"] == "pymupdf"
    warning = next(w for w in parsed.warnings if "Docling failed" in w)
    assert "layout model exploded" in warning and "read with PyMuPDF instead" in warning


def test_docling_page_cap_falls_back_to_pymupdf(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(dl, "docling_available", lambda artifacts: True)
    monkeypatch.setattr(dl, "parse_with_docling", lambda *a, **k: called.append(1))
    parsed = _parse(_im(), "im.pdf", pdf_parser="docling", docling_artifacts=str(tmp_path),
                    docling_max_pages=1, ocr_enabled=False)
    assert not called
    assert parsed.metadata["parser"] == "pymupdf"
    assert any("over the Docling cap of 1" in w and "read with PyMuPDF instead" in w
               for w in parsed.warnings)


def test_resolve_pdf_parser(tmp_path):
    assert resolve_pdf_parser("auto", str(tmp_path / "missing")) == "pymupdf"
    assert resolve_pdf_parser("auto", None) == "pymupdf"
    assert resolve_pdf_parser("docling", str(tmp_path / "missing")) == "docling"
    assert resolve_pdf_parser("pymupdf", str(tmp_path)) == "pymupdf"


# ------------------------------------------------------------------ vision model: which pages

def test_vlm_off_is_never_called(ocr_text):
    ocr_text(SHORT_OCR)
    fake = FakeVlm()
    parsed = _parse(_im(), "im.pdf", vlm=fake, scan_vlm="off")
    assert fake.calls == 0 and not parsed.model_runs


def test_vlm_fallback_reads_an_image_only_page_with_no_text():
    fake = FakeVlm("# Show cause notice\n\nDemand of INR 4.2 crore")
    parsed = _parse(_im(), "im.pdf", vlm=fake, scan_vlm="fallback", ocr_enabled=False)
    assert fake.calls == 1
    page3 = [b for b in parsed.blocks if b.page == 3]
    assert [b.kind for b in page3] == ["heading", "text"]
    assert page3[0].text == "Show cause notice" and page3[0].meta["source"] == "vlm"
    assert parsed.ocr_used
    # the PyMuPDF pages are untouched
    assert any(b.page == 1 and b.text == "Company overview" for b in parsed.blocks)


def test_vlm_fallback_skips_long_ocr_unless_the_name_is_flagged(ocr_text):
    ocr_text(LONG_OCR)
    fake = FakeVlm()
    parsed = _parse(_im(), "information_memorandum.pdf", vlm=fake, scan_vlm="fallback")
    assert fake.calls == 0 and not parsed.model_runs
    for name in ("kyc_scan.pdf", "board_resolution.pdf"):
        fake = FakeVlm()
        _parse(_im(), name, vlm=fake, scan_vlm="fallback")
        assert fake.calls == 1, name


def test_vlm_fallback_reads_thin_ocr(ocr_text):
    ocr_text(SHORT_OCR)
    fake = FakeVlm()
    _parse(_im(), "information_memorandum.pdf", vlm=fake, scan_vlm="fallback")
    assert fake.calls == 1


def test_vlm_always_reads_every_image_only_page(ocr_text):
    ocr_text(LONG_OCR)
    fake = FakeVlm()
    parsed = _parse(_im(), "information_memorandum.pdf", vlm=fake, scan_vlm="always")
    assert fake.calls == 1  # page 3 only: pages 1-2 have a text layer
    assert [r.kind for r in parsed.model_runs] == ["vlm_page"]

    fake = FakeVlm("Page text")
    parsed = _parse(_blank_pdf(3), "scan.pdf", vlm=fake, scan_vlm="always", ocr_enabled=False)
    assert fake.calls == 3
    assert sorted(b.page for b in parsed.blocks) == [1, 2, 3]


def test_vlm_max_pages_is_respected_with_a_warning():
    fake = FakeVlm("Page text")
    parsed = _parse(_blank_pdf(4), "scan.pdf", vlm=fake, scan_vlm="always", vlm_max_pages=2,
                    ocr_enabled=False)
    assert fake.calls == 2 and len(parsed.model_runs) == 2
    assert any("page limit of 2 reached" in w and "2 scanned page(s)" in w
               for w in parsed.warnings)


# ------------------------------------------------------------------ corroboration and failures

def test_vlm_numbers_confirmed_by_ocr_need_no_review(ocr_text):
    ocr_text(SHORT_OCR)
    parsed = _parse(_im(), "im.pdf", vlm=FakeVlm(), scan_vlm="fallback")
    page3 = [b for b in parsed.blocks if b.page == 3]
    assert page3 and all(b.meta.get("source") == "vlm" for b in page3)
    assert not any(b.meta.get("needs_review") for b in page3)
    assert any("numbers confirmed by OCR" in w for w in parsed.warnings)
    run = parsed.model_runs[0]
    assert (run.kind, run.status, run.model, run.batch_size, run.latency_ms) == \
        ("vlm_page", "ok", "fake-vlm:1b", 1, 42)
    assert run.error is None and run.input_chars == len(FakeVlm().markdown)
    assert not any(c.meta.get("needs_review") for c in chunk_document(parsed))


def test_vlm_number_not_in_ocr_marks_needs_review(ocr_text):
    ocr_text(SHORT_OCR)
    fake = FakeVlm("# Show cause notice\n\nDemand of INR 4.2 crore dated 12 March 2024\n\n"
                   "| Item | Amount |\n|---|---|\n| Penalty | 1,85,000 |")
    parsed = _parse(_im(), "im.pdf", vlm=fake, scan_vlm="fallback")
    page3 = [b for b in parsed.blocks if b.page == 3]
    assert [b.kind for b in page3] == ["heading", "text", "table"]
    assert all(b.meta["needs_review"] is True for b in page3)
    assert page3[0].meta["uncorroborated"] == ["185000"]
    assert any("needs review" in w and "185000" in w for w in parsed.warnings)
    chunks = [c for c in chunk_document(parsed) if c.page_from == 3]
    assert chunks and all(c.meta.get("needs_review") for c in chunks)
    assert {c.kind for c in chunks} == {"text", "table"}
    # chunks of the pages read by PyMuPDF are not flagged
    assert not any(c.meta.get("needs_review") for c in chunk_document(parsed)
                   if c.page_to and c.page_to < 3)


def test_vlm_failure_keeps_the_ocr_text(ocr_text):
    ocr_text(SHORT_OCR)
    fake = FakeVlm(fail=ConnectionError("ollama is down"))
    parsed = _parse(_im(), "im.pdf", vlm=fake, scan_vlm="fallback")
    page3 = " ".join(b.text for b in parsed.blocks if b.page == 3)
    assert "4.2 crore" in page3
    assert all(b.meta.get("source") == "ocr" for b in parsed.blocks if b.page == 3)
    assert any("page 3: vision model unavailable" in w and "kept the OCR text" in w
               for w in parsed.warnings)
    run = parsed.model_runs[0]
    assert run.kind == "vlm_page" and run.status == "error"
    assert "ConnectionError: ollama is down" in run.error and run.input_chars == 0


def test_vlm_empty_transcription_counts_as_failure(ocr_text):
    ocr_text(SHORT_OCR)
    parsed = _parse(_im(), "im.pdf", vlm=FakeVlm("   "), scan_vlm="fallback")
    assert parsed.model_runs[0].status == "error"
    assert "empty transcription" in parsed.model_runs[0].error
    assert any(b.meta.get("source") == "ocr" for b in parsed.blocks if b.page == 3)


# ------------------------------------------------------------------ helpers

def test_numbers_and_uncorroborated():
    assert numbers("INR 1,20,000 on 12/03/2024, 4.2 crore, item 7, 31.") == \
        ["120000", "12032024", "4.2", "31"]
    assert uncorroborated("Total 1,20,000 and 4.2", "total 120000 ... 4.2 crore") == []
    assert uncorroborated("Total 1,20,000 and 4.2 and 99", "total 120000") == ["4.2", "99"]
    assert uncorroborated("99 99 99", "") == ["99"]
    assert uncorroborated("no numbers here, 7", "") == []


def test_markdown_blocks_headings_tables_paragraphs():
    md = ("```markdown\n# **Borrowings** schedule\n\nAs at 31 March 2024\nAll in crore\n\n"
          "## Secured\n| Lender | Facility | Amount |\n| :--- | --- | ---: |\n"
          "| **State Bank of India** | Term loan | 45.20 |\n| HDFC Bank | CC | 12.00 |\n"
          "Closing note\n```")
    blocks = markdown_blocks(md, 4)
    assert [(b.kind, b.level) for b in blocks] == [("heading", 1), ("text", None),
                                                    ("heading", 2), ("table", None),
                                                    ("text", None)]
    assert blocks[0].text == "Borrowings schedule"
    assert blocks[1].text == "As at 31 March 2024\nAll in crore"
    assert blocks[3].rows == [["Lender", "Facility", "Amount"],
                              ["State Bank of India", "Term loan", "45.20"],
                              ["HDFC Bank", "CC", "12.00"]]
    assert blocks[4].text == "Closing note"
    assert all(b.page == 4 and b.meta["source"] == "vlm" for b in blocks)
    assert markdown_blocks("", 1) == [] and markdown_blocks("#\n", 1) == []


def test_ollama_vlm_sends_think_false_temperature_zero_and_takes_a_slot(monkeypatch):
    import httpx

    from aura.agents.llm import recording
    events, sent = [], {}

    class Slot:
        def release(self):
            events.append("release")

    def fake_slot(timeout):
        events.append(("acquire", timeout))
        return Slot()

    class Response:
        def raise_for_status(self):
            events.append("checked")

        def json(self):
            return {"message": {"content": "# Page"}}

    def fake_post(url, timeout, json):
        events.append("post")
        sent.update(url=url, timeout=timeout, body=json)
        return Response()

    monkeypatch.setattr(recording, "llm_slot", fake_slot)
    monkeypatch.setattr(httpx, "post", fake_post)
    reading = OllamaVlm("http://ollama:11434/", "qwen3.5:4b", timeout=30.0).read(b"\x89PNGdata")
    assert reading.markdown == "# Page" and reading.model == "qwen3.5:4b"
    assert events == [("acquire", 30.0), "post", "checked", "release"]
    body = sent["body"]
    assert sent["url"] == "http://ollama:11434/api/chat" and sent["timeout"] == 30.0
    assert body["think"] is False and body["stream"] is False
    assert body["options"]["temperature"] == 0
    assert body["model"] == "qwen3.5:4b"
    assert body["messages"][0]["images"] == [base64.b64encode(b"\x89PNGdata").decode()]


def test_ollama_vlm_releases_the_slot_on_error(monkeypatch):
    import httpx

    from aura.agents.llm import recording
    released = []

    class Slot:
        def release(self):
            released.append(True)

    def refuse(*a, **k):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(recording, "llm_slot", lambda timeout: Slot())
    monkeypatch.setattr(httpx, "post", refuse)
    with pytest.raises(httpx.ConnectError):
        OllamaVlm("http://x", "m").read(b"png")
    assert released == [True]


def test_vlm_block_meta_is_independent_per_block():
    a, b = Block("text", "x"), Block("text", "y")
    a.meta["needs_review"] = True
    assert "needs_review" not in b.meta
    assert vlm_mod.FLAGGED_NAME.search("Board-Resolution_signed.pdf")
    assert not vlm_mod.FLAGGED_NAME.search("information_memorandum.pdf")
