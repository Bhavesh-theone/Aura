"""Structure-aware chunking of a parsed document. Pure and deterministic: the same blocks give
the same chunks, byte for byte.

- A heading starts a new chunk (consecutive headings stay together with the body under them).
- Text is cut into windows of about `target_tokens` (4 characters per token) with
  `overlap_tokens` of overlap, breaking at a paragraph, sentence or word boundary.
- A table is never split mid-row: it is cut into groups of whole rows, each repeating the
  header row (or rows: block.meta['header_rows']); a single row longer than the target
  becomes a chunk of its own.
- Every chunk keeps the pages it spans (page_from/page_to) and its kind (text or table).
- A chunk made from any block marked needs_review (a vision-model reading OCR did not
  confirm) carries meta['needs_review'] = True.
"""
from dataclasses import dataclass

from aura.core.domain.ingest import Block, ChunkDraft, ParsedDocument

CHARS_PER_TOKEN = 4
DEFAULT_TARGET_TOKENS = 800
DEFAULT_OVERLAP_TOKENS = 100
_BREAKS = ("\n\n", "\n", ". ", "; ", ", ", " ")


@dataclass(frozen=True)
class ChunkingParams:
    target_tokens: int = DEFAULT_TARGET_TOKENS
    overlap_tokens: int = DEFAULT_OVERLAP_TOKENS

    @property
    def target_chars(self) -> int:
        return max(200, self.target_tokens * CHARS_PER_TOKEN)

    @property
    def overlap_chars(self) -> int:
        return max(0, min(self.overlap_tokens * CHARS_PER_TOKEN, self.target_chars // 2))


def approx_tokens(text: str) -> int:
    return (len(text) + CHARS_PER_TOKEN - 1) // CHARS_PER_TOKEN


def row_text(cells: list[str]) -> str:
    return " | ".join(" ".join(str(c or "").split()) for c in cells)


class _Section:
    """Text gathered under one heading: the joined text and the page of each part."""

    def __init__(self, heading: str | None):
        self.heading = heading
        self.parts: list[tuple[int, int, int | None]] = []  # (start, end, page)
        self.review: list[tuple[int, int]] = []  # spans from blocks marked needs_review
        self.text = ""
        self.has_body = False

    def add(self, text: str, page: int | None, body: bool = True,
            needs_review: bool = False) -> None:
        text = text.strip()
        if not text:
            return
        if self.text:
            self.text += "\n\n"
        start = len(self.text)
        self.text += text
        self.parts.append((start, len(self.text), page))
        if needs_review:
            self.review.append((start, len(self.text)))
        self.has_body = self.has_body or body

    def needs_review(self, start: int, end: int) -> bool:
        return any(s < end and e > start for s, e in self.review)

    def pages(self, start: int, end: int) -> tuple[int | None, int | None]:
        pages = [p for s, e, p in self.parts if p is not None and s < end and e > start]
        return (min(pages), max(pages)) if pages else (None, None)


def _cut(text: str, start: int, target: int) -> int:
    """End of the window that starts at `start`: at most `target` characters, ending at the
    best boundary in its second half."""
    end = start + target
    if end >= len(text):
        return len(text)
    floor = start + target // 2
    for sep in _BREAKS:
        at = text.rfind(sep, floor, end)
        if at != -1:
            return at + len(sep)
    return end


def _next_start(text: str, start: int, end: int, overlap: int) -> int:
    """Where the next window starts: `overlap` characters back from `end`, moved forward to
    the start of a word, never at or before `start`."""
    nxt = max(start + 1, end - overlap)
    if nxt < end and nxt > 0 and not text[nxt - 1].isspace():
        space = text.find(" ", nxt, end)
        nxt = space + 1 if space != -1 else end
    return min(nxt, end) if nxt > start else end


def _flush_text(section: _Section, params: ChunkingParams, out: list[ChunkDraft]) -> None:
    text = section.text
    if not text.strip():
        return
    start = 0
    while start < len(text):
        end = _cut(text, start, params.target_chars)
        piece = text[start:end].strip()
        if piece:
            page_from, page_to = section.pages(start, end)
            out.append(ChunkDraft(index=len(out), text=piece, kind="text",
                                  page_from=page_from, page_to=page_to,
                                  heading=section.heading,
                                  meta={"needs_review": True}
                                  if section.needs_review(start, end) else {}))
        if end >= len(text):
            break
        start = _next_start(text, start, end, params.overlap_chars)


def _table_rows(block: Block) -> list[str]:
    if block.rows:
        return [row_text(r) for r in block.rows if any(str(c or "").strip() for c in r)]
    return [line for line in (block.text or "").splitlines() if line.strip()]


def _flush_table(block: Block, heading: str | None, params: ChunkingParams,
                 out: list[ChunkDraft]) -> None:
    rows = _table_rows(block)
    if not rows:
        return
    n_header = int((block.meta or {}).get("header_rows") or 1)
    n_header = max(1, min(n_header, len(rows) - 1)) if len(rows) > 1 else 1
    header, body = "\n".join(rows[:n_header]), rows[n_header:]
    prefix = f"{heading}\n" if heading else ""
    if not body:
        groups = [[header]]
    else:
        groups, current = [], [header]
        size = len(prefix) + len(header)
        for row in body:
            if len(current) > 1 and size + 1 + len(row) > params.target_chars:
                groups.append(current)
                current, size = [header], len(prefix) + len(header)
            current.append(row)
            size += 1 + len(row)
        groups.append(current)
    for group in groups:
        meta = {"rows": len(group) - 1 if body else 0, "header": header}
        if (block.meta or {}).get("columns"):
            meta["columns"] = list(block.meta["columns"])
        if (block.meta or {}).get("needs_review"):
            meta["needs_review"] = True
        out.append(ChunkDraft(index=len(out), text=prefix + "\n".join(group), kind="table",
                              page_from=block.page, page_to=block.page, heading=heading,
                              meta=meta))


def chunk_document(parsed: ParsedDocument,
                   params: ChunkingParams = ChunkingParams()) -> list[ChunkDraft]:
    out: list[ChunkDraft] = []
    section = _Section(None)
    for block in parsed.blocks:
        if block.kind == "heading":
            title = " ".join((block.text or "").split())
            if not title:
                continue
            if section.has_body:
                _flush_text(section, params, out)
                section = _Section(title)
            elif not section.text:
                section = _Section(title)
            else:  # headings with no body yet: they stay together, the latest names it
                section.heading = title
            section.add(title, block.page, body=False)
        elif block.kind == "table":
            if section.has_body:
                _flush_text(section, params, out)
                section = _Section(section.heading)
            heading = section.heading
            _flush_table(block, heading, params, out)
            section = _Section(heading)
        else:
            section.add(block.text or "", block.page,
                        needs_review=bool((block.meta or {}).get("needs_review")))
    if section.has_body or (section.text and not out):
        _flush_text(section, params, out)
    return out
