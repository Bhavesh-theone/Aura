"""Document parsers: the DocumentParser port for every format Aura reads.

    PDF   PyMuPDF, per-page text with font-size headings; pages with no text layer are read
          by OCR (RapidOCR, local ONNX models) up to ocr_max_pages
    DOCX  python-docx: paragraphs, headings (Heading/Title styles) and tables, in order
    XLSX  openpyxl: each sheet's used range as a table (header row kept)
    CSV   csv: one table
    PPTX  python-pptx: per slide, title, text, tables and speaker notes
    EML   email (stdlib): headers, plain or HTML body, attachments listed and parsed
    MSG   extract-msg: as EML
    TXT/MD  plain text; Markdown '#' lines are headings

The format is chosen by extension and checked against the file's magic bytes. A file named
.pdf (or .docx, ...) whose content is plain text is read as text, with a warning. Anything
unreadable raises a typed IngestError (UnsupportedFormat, CorruptDocument, DocumentTooLarge),
never a bare exception.
"""
import csv
import email
import html
import io
import logging
import re
import threading
import zipfile
from dataclasses import dataclass
from datetime import datetime
from email import policy
from html.parser import HTMLParser
from pathlib import PurePath

from aura.core.domain.ingest import (Block, CorruptDocument, DocumentTooLarge, IngestError,
                                     ParsedDocument, UnsupportedFormat)

logger = logging.getLogger(__name__)

FORMATS = {".pdf": "pdf", ".docx": "docx", ".xlsx": "xlsx", ".xlsm": "xlsx", ".csv": "csv",
           ".pptx": "pptx", ".eml": "eml", ".msg": "msg", ".txt": "txt", ".md": "md",
           ".markdown": "md"}
MIME = {"application/pdf": "pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
        "text/csv": "csv", "message/rfc822": "eml", "application/vnd.ms-outlook": "msg",
        "text/plain": "txt", "text/markdown": "md"}
_OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
MAX_SHEET_ROWS = 20_000
MAX_ATTACHMENT_DEPTH = 2


@dataclass(frozen=True)
class ParserLimits:
    max_upload_mb: int = 25
    max_pages: int = 300
    ocr_enabled: bool = True
    ocr_max_pages: int = 50
    ocr_min_chars: int = 25

    @property
    def max_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


def limits_from_settings() -> ParserLimits:
    from aura.config import get_settings
    s = get_settings()
    return ParserLimits(max_upload_mb=s.max_upload_mb, max_pages=s.max_pages,
                        ocr_enabled=s.ocr_enabled, ocr_max_pages=s.ocr_max_pages,
                        ocr_min_chars=s.ocr_min_chars)


def extension(filename: str) -> str:
    return PurePath(filename or "").suffix.lower()


def supported_extensions() -> list[str]:
    return sorted(FORMATS)


def _looks_like_text(content: bytes) -> bool:
    head = content[:4096]
    if not head or b"\x00" in head:
        return False
    try:
        head.decode("utf-8")
        return True
    except UnicodeDecodeError as exc:  # a multi-byte character cut at the boundary is fine
        if exc.start >= len(head) - 4:
            return True
    printable = sum(1 for b in head if b in (9, 10, 13) or 32 <= b < 127 or b >= 160)
    return printable / len(head) > 0.95


def sniff(content: bytes) -> str | None:
    """The format the bytes look like, or None."""
    if content.startswith(b"%PDF"):
        return "pdf"
    if content.startswith(b"PK\x03\x04"):
        try:
            names = zipfile.ZipFile(io.BytesIO(content)).namelist()
        except zipfile.BadZipFile:
            return None
        for prefix, kind in (("word/", "docx"), ("xl/", "xlsx"), ("ppt/", "pptx")):
            if any(n.startswith(prefix) for n in names):
                return kind
        return None
    if content.startswith(_OLE):
        return "msg"
    if _looks_like_text(content):
        head = content[:2048].decode("utf-8", errors="replace")
        if re.search(r"^(From|Received|Message-ID|MIME-Version|Subject|Return-Path):",
                     head, re.MULTILINE | re.IGNORECASE) and "\n\n" in \
                content[:65536].decode("utf-8", errors="replace").replace("\r\n", "\n"):
            return "eml"
        return "txt"
    return None


def detect(content: bytes, filename: str, mime: str | None = None) -> tuple[str, list[str]]:
    """(format, warnings). Extension first, checked against the magic bytes."""
    ext = extension(filename)
    claimed = FORMATS.get(ext) or MIME.get((mime or "").split(";")[0].strip().lower())
    actual = sniff(content)
    if claimed is None:
        if ext and ext not in ("",):
            raise UnsupportedFormat(
                f"{filename}: {ext} files are not supported (supported: "
                f"{', '.join(supported_extensions())})")
        if actual is None:
            raise UnsupportedFormat(f"{filename}: unrecognised file type")
        return actual, []
    if claimed in ("txt", "md", "csv", "eml"):
        if actual not in ("txt", "eml"):
            raise CorruptDocument(f"{filename}: not a text file")
        return claimed, []
    if actual == claimed:
        return claimed, []
    if actual in ("txt", "eml"):
        return actual, [f"the content is plain text, not {claimed.upper()}; read as text"]
    raise CorruptDocument(f"{filename}: the content is not a valid {claimed.upper()} file")


def check_upload(filename: str, content: bytes, limits: ParserLimits | None = None) -> str:
    """Refuse an upload Aura could never index: unsupported type (415) or too large (413).
    Returns the format. Content problems beyond the type are left to the indexer."""
    limits = limits or limits_from_settings()
    if len(content) > limits.max_bytes:
        raise DocumentTooLarge(f"{filename}: {len(content) / 1048576:.1f} MB is over the "
                               f"{limits.max_upload_mb} MB upload limit")
    ext = extension(filename)
    if ext and ext not in FORMATS:
        raise UnsupportedFormat(f"{ext} files are not supported (supported: "
                                f"{', '.join(supported_extensions())})")
    if not ext and sniff(content) is None:
        raise UnsupportedFormat(f"{filename}: unrecognised file type")
    return FORMATS.get(ext) or sniff(content) or "txt"


def decode_text(content: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace")


def _clean(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else f"{value:.6g}" \
            if abs(value) < 1e15 else str(value)
    if isinstance(value, datetime):
        return value.date().isoformat() if value.time() == datetime.min.time() \
            else value.isoformat(sep=" ")
    return " ".join(str(value).split())


def _trim_table(rows: list[list[str]]) -> list[list[str]]:
    rows = [r for r in rows if any(c for c in r)]
    if not rows:
        return []
    width = max(max((i + 1 for i, c in enumerate(r) if c), default=0) for r in rows)
    lead = min(next((i for i, c in enumerate(r) if c), width) for r in rows)
    return [(r + [""] * width)[lead:width] for r in rows]


def _table_block(rows: list[list[str]], page: int | None = None) -> Block:
    rows = _trim_table(rows)
    return Block(kind="table", text="\n".join(" | ".join(r) for r in rows), page=page,
                 rows=rows)


def _paragraph_blocks(text: str, page: int | None = None, markdown: bool = False
                      ) -> list[Block]:
    blocks: list[Block] = []
    for para in re.split(r"\n\s*\n", _clean(text)):
        para = para.strip()
        if not para:
            continue
        if markdown:
            lines, body = para.split("\n"), []
            for line in lines:
                m = re.match(r"^(#{1,6})\s+(.*)$", line)
                if m:
                    if body:
                        blocks.append(Block("text", "\n".join(body), page))
                        body = []
                    blocks.append(Block("heading", m.group(2).strip(), page,
                                        level=len(m.group(1))))
                else:
                    body.append(line)
            if body:
                blocks.append(Block("text", "\n".join(body), page))
        else:
            blocks.append(Block("text", para, page))
    return blocks


# ------------------------------------------------------------------ OCR

class _Ocr:
    """RapidOCR (ONNX models shipped in the wheel), loaded once, one page at a time."""
    _lock = threading.Lock()
    _engine = None
    _failed: str | None = None

    @classmethod
    def read(cls, png: bytes) -> str:
        with cls._lock:
            if cls._engine is None and cls._failed is None:
                try:
                    from rapidocr_onnxruntime import RapidOCR
                    cls._engine = RapidOCR()
                except Exception as exc:  # pragma: no cover - depends on the machine
                    cls._failed = f"{type(exc).__name__}: {exc}"
            if cls._engine is None:
                raise RuntimeError(f"OCR unavailable ({cls._failed})")
            result, _ = cls._engine(png)
        lines = sorted(result or [], key=lambda r: (round(r[0][0][1] / 12), r[0][0][0]))
        return "\n".join(r[1] for r in lines if r[1] and r[2] >= 0.5)


def ocr_available() -> bool:
    try:
        import rapidocr_onnxruntime  # noqa: F401
        return True
    except Exception:
        return False


# ------------------------------------------------------------------ formats

def parse_pdf(content: bytes, limits: ParserLimits) -> ParsedDocument:
    import fitz  # PyMuPDF
    try:
        doc = fitz.open(stream=content, filetype="pdf")
    except Exception as exc:
        raise CorruptDocument(f"the PDF cannot be opened ({exc})") from exc
    with doc:
        if doc.needs_pass:
            raise CorruptDocument("the PDF is password-protected")
        if doc.page_count > limits.max_pages:
            raise DocumentTooLarge(f"{doc.page_count} pages is over the {limits.max_pages}-page "
                                   "limit")
        warnings: list[str] = []
        pages = []
        sizes: dict[float, int] = {}
        for page in doc:
            try:
                data = page.get_text("dict", flags=0)
            except Exception as exc:
                warnings.append(f"page {page.number + 1}: text could not be read ({exc})")
                data = {"blocks": []}
            found = []
            for block in data.get("blocks", []):
                if block.get("type", 0) != 0:
                    continue
                lines, size = [], 0.0
                for line in block.get("lines", []):
                    spans = [s for s in line.get("spans", []) if s.get("text", "").strip()]
                    if not spans:
                        continue
                    lines.append("".join(s["text"] for s in line["spans"]).strip())
                    for s in spans:
                        rounded = round(s.get("size", 0), 1)
                        sizes[rounded] = sizes.get(rounded, 0) + len(s["text"])
                        size = max(size, rounded)
                if lines:
                    found.append(("\n".join(lines), size))
            pages.append(found)
        body_size = max(sizes, key=lambda k: sizes[k]) if sizes else 0
        blocks: list[Block] = []
        ocr_pages = 0
        for number, found in enumerate(pages, start=1):
            chars = sum(len(t.strip()) for t, _ in found)
            if chars < limits.ocr_min_chars:
                if not limits.ocr_enabled:
                    warnings.append(f"page {number}: no text layer (OCR is off)")
                elif ocr_pages >= limits.ocr_max_pages:
                    warnings.append(f"page {number}: no text layer; OCR limit of "
                                    f"{limits.ocr_max_pages} pages reached")
                else:
                    ocr_pages += 1
                    try:
                        pix = doc[number - 1].get_pixmap(dpi=200)
                        text = _Ocr.read(pix.tobytes("png"))
                    except Exception as exc:
                        warnings.append(f"page {number}: OCR failed ({exc})")
                        text = ""
                    if text.strip():
                        warnings.append(f"page {number}: text recognised by OCR")
                        blocks += _paragraph_blocks(text, number)
                        continue
                    if not found:
                        warnings.append(f"page {number}: no text found")
            for text, size in found:
                one_line = "\n" not in text.strip() and len(text) <= 120
                if body_size and size >= body_size * 1.2 and one_line and \
                        re.search(r"[A-Za-z]", text):
                    blocks.append(Block("heading", _clean(text), number))
                else:
                    blocks.append(Block("text", _clean(text), number))
        meta = {k: v for k, v in (doc.metadata or {}).items() if v}
        return ParsedDocument(blocks=blocks, metadata=meta, page_count=doc.page_count,
                              ocr_used=ocr_pages > 0 and any("OCR" in w and "recognised" in w
                                                             for w in warnings),
                              warnings=warnings)


def parse_docx(content: bytes, limits: ParserLimits) -> ParsedDocument:
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph
    try:
        document = docx.Document(io.BytesIO(content))
    except Exception as exc:
        raise CorruptDocument(f"the DOCX cannot be opened ({exc})") from exc
    blocks: list[Block] = []
    body = document.element.body
    for child in body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            p = Paragraph(child, document)
            text = _clean(p.text)
            if not text:
                continue
            style = (p.style.name if p.style is not None else "") or ""
            m = re.match(r"(Heading|Title)\s*(\d*)", style)
            if m:
                blocks.append(Block("heading", text, None,
                                    level=int(m.group(2)) if m.group(2) else 1))
            else:
                blocks.append(Block("text", text))
        elif tag == "tbl":
            table = Table(child, document)
            rows = []
            for row in table.rows:
                cells, seen = [], set()
                for cell in row.cells:  # merged cells repeat: keep each once
                    if id(cell._tc) in seen:
                        continue
                    seen.add(id(cell._tc))
                    cells.append(_cell(cell.text))
                rows.append(cells)
            block = _table_block(rows)
            if block.rows:
                blocks.append(block)
    props = document.core_properties
    meta = {k: getattr(props, k) for k in ("title", "author", "subject")
            if getattr(props, k, None)}
    return ParsedDocument(blocks=blocks, metadata=meta)


def parse_xlsx(content: bytes, limits: ParserLimits) -> ParsedDocument:
    import openpyxl
    try:
        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception as exc:
        raise CorruptDocument(f"the workbook cannot be opened ({exc})") from exc
    blocks: list[Block] = []
    warnings: list[str] = []
    try:
        for ws in wb.worksheets:
            rows = []
            for i, row in enumerate(ws.iter_rows(values_only=True)):
                if i >= MAX_SHEET_ROWS:
                    warnings.append(f"sheet '{ws.title}': only the first {MAX_SHEET_ROWS} "
                                    "rows were indexed")
                    break
                rows.append([_cell(v) for v in row])
            table = _table_block(rows)
            if not table.rows:
                warnings.append(f"sheet '{ws.title}' is empty")
                continue
            blocks.append(Block("heading", f"Sheet: {ws.title}"))
            blocks.append(table)
    finally:
        wb.close()
    return ParsedDocument(blocks=blocks, metadata={"sheets": len(blocks) // 2},
                          warnings=warnings)


def parse_csv(content: bytes, limits: ParserLimits) -> ParsedDocument:
    text = decode_text(content)
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    rows = [[_cell(c) for c in r] for r in csv.reader(io.StringIO(text), dialect)]
    warnings = []
    if len(rows) > MAX_SHEET_ROWS:
        rows = rows[:MAX_SHEET_ROWS]
        warnings.append(f"only the first {MAX_SHEET_ROWS} rows were indexed")
    table = _table_block(rows)
    return ParsedDocument(blocks=[table] if table.rows else [], warnings=warnings)


def parse_pptx(content: bytes, limits: ParserLimits) -> ParsedDocument:
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE_TYPE
    try:
        deck = Presentation(io.BytesIO(content))
    except Exception as exc:
        raise CorruptDocument(f"the presentation cannot be opened ({exc})") from exc
    slides = list(deck.slides)
    if len(slides) > limits.max_pages:
        raise DocumentTooLarge(f"{len(slides)} slides is over the {limits.max_pages} limit")
    blocks: list[Block] = []

    def shapes_of(shapes):
        for shape in shapes:
            if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
                yield from shapes_of(shape.shapes)
            else:
                yield shape

    for number, slide in enumerate(slides, start=1):
        title_shape = slide.shapes.title
        title = _clean(title_shape.text_frame.text) if title_shape is not None and \
            title_shape.has_text_frame else ""
        blocks.append(Block("heading", f"Slide {number}: {title}" if title
                            else f"Slide {number}", number))
        for shape in shapes_of(slide.shapes):
            if title_shape is not None and shape.shape_id == title_shape.shape_id:
                continue
            if getattr(shape, "has_table", False) and shape.has_table:
                rows = [[_cell(c.text) for c in r.cells] for r in shape.table.rows]
                block = _table_block(rows, number)
                if block.rows:
                    blocks.append(block)
            elif shape.has_text_frame:
                text = _clean(shape.text_frame.text)
                if text:
                    blocks.append(Block("text", text, number))
        if slide.has_notes_slide:
            notes = _clean(slide.notes_slide.notes_text_frame.text
                           if slide.notes_slide.notes_text_frame else "")
            if notes:
                blocks.append(Block("text", f"Speaker notes: {notes}", number))
    return ParsedDocument(blocks=blocks, page_count=len(slides),
                          metadata={"slides": len(slides)})


class _HtmlText(HTMLParser):
    _BREAK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "table",
              "ul", "ol", "section", "article", "blockquote"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "head"):
            self._skip += 1
        elif tag in self._BREAK:
            self.parts.append("\n")
        elif tag in ("td", "th"):
            self.parts.append(" | ")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "head"):
            self._skip = max(0, self._skip - 1)
        elif tag in self._BREAK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def html_to_text(markup: str) -> str:
    parser = _HtmlText()
    try:
        parser.feed(markup)
        parser.close()
    except Exception:
        return html.unescape(re.sub(r"<[^>]+>", " ", markup))
    return _clean("".join(parser.parts))


def _email_blocks(headers: list[tuple[str, str]], subject: str, body: str,
                  attachments: list[tuple[str, bytes]], limits: ParserLimits, depth: int
                  ) -> ParsedDocument:
    blocks = [Block("heading", subject or "(no subject)")]
    head = "\n".join(f"{k}: {v}" for k, v in headers if v)
    if head:
        blocks.append(Block("text", head))
    blocks += _paragraph_blocks(body)
    warnings: list[str] = []
    ocr_used = False
    if attachments:
        listing = ", ".join(f"{name} ({max(1, len(data) // 1024)} KB)"
                            for name, data in attachments)
        blocks.append(Block("text", f"Attachments: {listing}"))
    for name, data in attachments:
        if depth >= MAX_ATTACHMENT_DEPTH:
            warnings.append(f"attachment {name}: nested too deep, not read")
            continue
        try:
            inner = parse(data, name, limits=limits, _depth=depth + 1)
        except UnsupportedFormat:
            warnings.append(f"attachment {name}: format not supported, listed only")
            continue
        except IngestError as exc:
            warnings.append(f"attachment {name}: {exc}")
            continue
        blocks.append(Block("heading", f"Attachment: {name}"))
        blocks += [Block(b.kind, b.text, None, b.rows, b.level) for b in inner.blocks]
        warnings += [f"attachment {name}: {w}" for w in inner.warnings]
        ocr_used = ocr_used or inner.ocr_used
    return ParsedDocument(blocks=blocks, warnings=warnings, ocr_used=ocr_used,
                          metadata={"subject": subject, "attachments": len(attachments)})


def parse_eml(content: bytes, limits: ParserLimits, depth: int = 0) -> ParsedDocument:
    try:
        msg = email.message_from_bytes(content, policy=policy.default)
    except Exception as exc:
        raise CorruptDocument(f"the email cannot be read ({exc})") from exc
    headers = [(k, str(msg.get(k, "") or "")) for k in ("From", "To", "Cc", "Date",
                                                          "Subject")]
    body = ""
    try:
        part = msg.get_body(preferencelist=("plain", "html"))
        if part is not None:
            text = part.get_content()
            body = html_to_text(text) if part.get_content_type() == "text/html" else text
    except Exception:
        body = decode_text(msg.get_payload(decode=True) or b"") if not msg.is_multipart() \
            else ""
    attachments = []
    for att in msg.iter_attachments():
        name = att.get_filename() or "attachment"
        try:
            data = att.get_payload(decode=True) or b""
        except Exception:
            data = b""
        attachments.append((name, data))
    return _email_blocks(headers, str(msg.get("Subject", "") or ""), body, attachments,
                         limits, depth)


def parse_msg(content: bytes, limits: ParserLimits, depth: int = 0) -> ParsedDocument:
    import extract_msg
    try:
        msg = extract_msg.Message(content)
    except Exception as exc:
        raise CorruptDocument(f"the Outlook message cannot be read ({exc})") from exc
    try:
        body = msg.body or ""
        if not body.strip() and getattr(msg, "htmlBody", None):
            raw = msg.htmlBody
            body = html_to_text(raw.decode("utf-8", errors="replace")
                                if isinstance(raw, bytes) else str(raw))
        headers = [("From", msg.sender or ""), ("To", msg.to or ""), ("Cc", msg.cc or ""),
                   ("Date", str(msg.date or "")), ("Subject", msg.subject or "")]
        attachments = []
        for att in msg.attachments:
            data = getattr(att, "data", None)
            if isinstance(data, bytes):
                name = getattr(att, "longFilename", None) or getattr(att, "shortFilename",
                                                                     None) or "attachment"
                attachments.append((name, data))
        return _email_blocks(headers, msg.subject or "", body, attachments, limits, depth)
    finally:
        try:
            msg.close()
        except Exception:
            pass


def parse_text(content: bytes, limits: ParserLimits, markdown: bool = False
               ) -> ParsedDocument:
    return ParsedDocument(blocks=_paragraph_blocks(decode_text(content), None, markdown))


def parse(content: bytes, filename: str, mime: str | None = None,
          limits: ParserLimits | None = None, _depth: int = 0) -> ParsedDocument:
    limits = limits or limits_from_settings()
    if len(content) > limits.max_bytes:
        raise DocumentTooLarge(f"{len(content) / 1048576:.1f} MB is over the "
                               f"{limits.max_upload_mb} MB limit")
    if not content:
        raise CorruptDocument(f"{filename}: the file is empty")
    kind, warnings = detect(content, filename, mime)
    try:
        if kind == "pdf":
            parsed = parse_pdf(content, limits)
        elif kind == "docx":
            parsed = parse_docx(content, limits)
        elif kind == "xlsx":
            parsed = parse_xlsx(content, limits)
        elif kind == "csv":
            parsed = parse_csv(content, limits)
        elif kind == "pptx":
            parsed = parse_pptx(content, limits)
        elif kind == "eml":
            parsed = parse_eml(content, limits, _depth)
        elif kind == "msg":
            parsed = parse_msg(content, limits, _depth)
        else:
            parsed = parse_text(content, limits, markdown=kind == "md")
    except IngestError:
        raise
    except Exception as exc:  # a library failing on a damaged file is a corrupt document
        logger.warning("parser %s failed on %s", kind, filename, exc_info=True)
        raise CorruptDocument(f"{filename}: could not be read as {kind.upper()} "
                              f"({type(exc).__name__}: {exc})") from exc
    parsed.warnings = warnings + parsed.warnings
    parsed.metadata.setdefault("format", kind)
    return parsed


class FormatRegistryParser:
    """The DocumentParser port: format by extension and magic bytes, limits from settings."""

    def __init__(self, limits: ParserLimits | None = None):
        self.limits = limits

    def parse(self, content: bytes, filename: str, mime: str | None = None) -> ParsedDocument:
        return parse(content, filename, mime, self.limits or limits_from_settings())
