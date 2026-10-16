"""PDF rendering (reportlab): an A4 deal report in the Ledger look — Newsreader headings,
Inter text, hairline tables — with a header and footer on every page (deal id, page x of y,
generated at, Confidential) and a diagonal UPSI watermark when the deal holds UPSI.

Fonts are bundled (aura/exports/fonts, SIL OFL). If they cannot be loaded the report falls
back to Helvetica and writes 'Rs' for the rupee sign, which Helvetica lacks."""
import io
from functools import cache
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, CondPageBreak, Frame, KeepTogether,
                                PageTemplate, Paragraph, Spacer, Table, TableStyle)

from aura.core.domain.export import DealExportBundle, ExportSection, ExportTable
from aura.exports.common import RenderedExport, human_cell, human_datetime, humanize

FONT_DIR = Path(__file__).resolve().parent / "fonts"
INK = colors.HexColor("#14171A")
INK_2 = colors.HexColor("#4A5158")
MUTED = colors.HexColor("#676E75")
LINE = colors.HexColor("#E6E4DF")
WELL = colors.HexColor("#F4F3EF")
ACCENT = colors.HexColor("#1F4FD8")
DANGER = colors.HexColor("#B42318")
NUMERIC = ("inr", "int", "float", "pct")
MARGIN_X, MARGIN_TOP, MARGIN_BOTTOM = 18 * mm, 22 * mm, 18 * mm


@cache
def fonts() -> dict:
    """Register the bundled fonts once. Returns the face names to use."""
    try:
        for name, file in (("AuraSans", "Inter-Regular.ttf"),
                           ("AuraSans-Bold", "Inter-SemiBold.ttf"),
                           ("AuraSerif", "Newsreader-Regular.ttf"),
                           ("AuraSerif-Bold", "Newsreader-SemiBold.ttf")):
            pdfmetrics.registerFont(TTFont(name, str(FONT_DIR / file)))
        pdfmetrics.registerFontFamily("AuraSans", normal="AuraSans", bold="AuraSans-Bold",
                                      italic="AuraSans", boldItalic="AuraSans-Bold")
        return {"sans": "AuraSans", "bold": "AuraSans-Bold", "serif": "AuraSerif",
                "serif_bold": "AuraSerif-Bold", "rupee": True}
    except Exception:  # missing or unreadable font files: still produce a report
        return {"sans": "Helvetica", "bold": "Helvetica-Bold", "serif": "Times-Roman",
                "serif_bold": "Times-Bold", "rupee": False}


def _text(value: str, markup: bool = True) -> str:
    """Escaped paragraph text. Newsreader has no rupee sign, so a ₹ is always set in the sans
    face; without the bundled fonts it becomes 'Rs '."""
    s = escape(value or "") if markup else (value or "")
    if not fonts()["rupee"]:
        return s.replace("₹", "Rs ")
    return s.replace("₹", f'<font name="{fonts()["sans"]}">₹</font>') if markup else s


def _styles() -> dict:
    f = fonts()
    return {
        "kicker": ParagraphStyle("kicker", fontName=f["sans"], fontSize=8.5, leading=11,
                                 textColor=MUTED),
        "title": ParagraphStyle("title", fontName=f["serif"], fontSize=26, leading=30,
                                textColor=INK, spaceBefore=4, spaceAfter=2),
        "subtitle": ParagraphStyle("subtitle", fontName=f["sans"], fontSize=9.5, leading=13,
                                   textColor=INK_2),
        "h2": ParagraphStyle("h2", fontName=f["serif"], fontSize=15, leading=19,
                             textColor=INK, spaceBefore=14, spaceAfter=6),
        "h3": ParagraphStyle("h3", fontName=f["bold"], fontSize=8.5, leading=11,
                             textColor=INK, spaceBefore=8, spaceAfter=4),
        "note": ParagraphStyle("note", fontName=f["sans"], fontSize=7.5, leading=10,
                               textColor=MUTED, spaceAfter=3),
        "warn": ParagraphStyle("warn", fontName=f["bold"], fontSize=8.5, leading=11.5,
                               textColor=DANGER),
        "cell": ParagraphStyle("cell", fontName=f["sans"], fontSize=7.4, leading=9.4,
                               textColor=INK),
        "cell_r": ParagraphStyle("cell_r", fontName=f["sans"], fontSize=7.4, leading=9.4,
                                 textColor=INK, alignment=TA_RIGHT),
        "head": ParagraphStyle("head", fontName=f["bold"], fontSize=7, leading=9,
                               textColor=MUTED),
        "head_r": ParagraphStyle("head_r", fontName=f["bold"], fontSize=7, leading=9,
                                 textColor=MUTED, alignment=TA_RIGHT),
        "fact_label": ParagraphStyle("fact_label", fontName=f["sans"], fontSize=7.4,
                                     leading=9.5, textColor=MUTED),
        "fact_value": ParagraphStyle("fact_value", fontName=f["sans"], fontSize=8.6,
                                     leading=11, textColor=INK),
    }


def _facts(facts: list[tuple[str, str]], width: float, st: dict, cols: int = 4):
    cells = [[Paragraph(_text(label), st["fact_label"]),
              Paragraph(_text(value) or "—", st["fact_value"])] for label, value in facts]
    rows = []
    for i in range(0, len(cells), cols):
        chunk = cells[i:i + cols] + [["", ""]] * (cols - len(cells[i:i + cols]))
        rows.append([c[0] for c in chunk])
        rows.append([c[1] for c in chunk])
    t = Table(rows, colWidths=[width / cols] * cols, hAlign="LEFT")
    style = [("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
             ("RIGHTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 0),
             ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]
    for r in range(1, len(rows), 2):
        style.append(("BOTTOMPADDING", (0, r), (-1, r), 7))
    t.setStyle(TableStyle(style))
    return t


def _table(table: ExportTable, width: float, st: dict) -> list:
    out = [Paragraph(_text(table.title), st["h3"])]
    if table.note:
        out.append(Paragraph(_text(table.note), st["note"]))
    if not table.rows:
        out.append(Paragraph("None recorded.", st["note"]))
        return out
    cols = [c for c in table.columns if c.human]
    total = sum(c.width for c in cols) or 1
    widths = [width * c.width / total for c in cols]
    data = [[Paragraph(_text(c.label), st["head_r" if c.type in NUMERIC else "head"])
             for c in cols]]
    for row in table.rows:
        data.append([Paragraph(_text(human_cell(row.get(c.key), c.type)),
                               st["cell_r" if c.type in NUMERIC else "cell"])
                     for c in cols])
    t = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), WELL),
        ("LINEABOVE", (0, 0), (-1, 0), 0.6, LINE),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
    ]))
    out.append(t)
    if table.truncated:
        out.append(Paragraph("Truncated: more rows exist than an export carries.", st["note"]))
    return out


def _section(section: ExportSection, width: float, st: dict) -> list:
    flow: list = [CondPageBreak(40 * mm)]
    heading = [Paragraph(_text(section.title), st["h2"])]
    if section.facts:
        heading.append(_facts(section.facts, width, st))
    tables = [(t, _table(t, width, st)) for t in section.tables]
    if tables and len(tables[0][0].rows) <= 14:
        # The heading never ends a page alone: it stays with its first (short) table.
        flow.append(KeepTogether(heading + tables.pop(0)[1]))
    else:
        for h in heading:
            h.keepWithNext = True
        flow += heading
    for table, parts in tables:
        if len(table.rows) <= 14:
            flow.append(KeepTogether(parts))
        else:  # a long table splits across pages (its header row repeats); title stays on
            for part in parts[:-1]:
                part.keepWithNext = True
            flow += parts
    return flow


class _Doc(BaseDocTemplate):
    """Two passes: the first counts pages so the footer can say 'page x of y'."""

    def __init__(self, buf, bundle: DealExportBundle, total_pages: int | None):
        super().__init__(buf, pagesize=A4, leftMargin=MARGIN_X, rightMargin=MARGIN_X,
                         topMargin=MARGIN_TOP, bottomMargin=MARGIN_BOTTOM,
                         title=f"{bundle.deal['external_id']} {bundle.deal['name']}",
                         author=bundle.generated_by, subject="Aura deal report",
                         creator="Aura")
        self.bundle, self.total_pages = bundle, total_pages
        frame = Frame(self.leftMargin, self.bottomMargin, self.width, self.height, id="body",
                      leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
        self.addPageTemplates([PageTemplate(id="page", frames=[frame],
                                            onPage=self._decorate)])

    def _decorate(self, canvas, doc) -> None:
        f, b = fonts(), self.bundle
        w, h = A4
        canvas.saveState()
        if b.upsi:
            canvas.saveState()
            canvas.setFillColor(DANGER)
            canvas.setFillAlpha(0.07)
            canvas.setFont(f["bold"], 92)
            canvas.translate(w / 2, h / 2)
            canvas.rotate(35)
            canvas.drawCentredString(0, -30, "UPSI")
            canvas.setFont(f["bold"], 22)
            canvas.drawCentredString(0, -62, "CONFIDENTIAL · RESTRICTED")
            canvas.restoreState()
        top = h - 12 * mm
        canvas.setFont(f["bold"], 7.5)
        canvas.setFillColor(INK)
        canvas.drawString(MARGIN_X, top, b.deal["external_id"])
        canvas.setFont(f["sans"], 7.5)
        canvas.setFillColor(MUTED)
        canvas.drawString(MARGIN_X + canvas.stringWidth(b.deal["external_id"], f["bold"], 7.5)
                          + 6, top, _text(b.deal["name"][:70], markup=False))
        label = "CONFIDENTIAL" + (" · UPSI" if b.upsi else "")
        canvas.setFont(f["bold"], 7)
        canvas.setFillColor(DANGER if b.upsi else MUTED)
        canvas.drawRightString(w - MARGIN_X, top, label)
        canvas.setStrokeColor(LINE)
        canvas.setLineWidth(0.5)
        canvas.line(MARGIN_X, top - 3 * mm, w - MARGIN_X, top - 3 * mm)
        bottom = 10 * mm
        canvas.line(MARGIN_X, bottom + 4 * mm, w - MARGIN_X, bottom + 4 * mm)
        canvas.setFont(f["sans"], 7)
        canvas.setFillColor(MUTED)
        canvas.drawString(MARGIN_X, bottom, _text(
            f"Generated {human_datetime(b.generated_at)} IST by {b.generated_by} · Aura",
            markup=False))
        total = self.total_pages or "?"
        canvas.drawRightString(w - MARGIN_X, bottom, f"Page {doc.page} of {total}")
        canvas.restoreState()


def _story(bundle: DealExportBundle, width: float) -> list:
    st = _styles()
    d = bundle.deal
    outcome = f" · {humanize(d['outcome'])}" if d.get("outcome") else ""
    story: list = [
        Paragraph(_text(f"{d['external_id']}  ·  {d['transaction_class']}  ·  "
                        f"{humanize(d['stage'])}{outcome}"), st["kicker"]),
        Paragraph(_text(d["name"]), st["title"]),
        Paragraph(_text(f"Deal report · prepared for {bundle.generated_by} "
                        f"({bundle.generated_by_role}) · {human_datetime(bundle.generated_at)} "
                        f"IST · {len(bundle.sections)} sections"),
                  st["subtitle"]),
        Spacer(1, 4 * mm),
    ]
    if bundle.upsi:
        story += [Paragraph("This report contains unpublished price-sensitive information "
                            "(UPSI). Handle it under the insider-trading code and do not "
                            "forward it outside the deal wall.", st["warn"]),
                  Spacer(1, 2 * mm)]
    for section in bundle.sections:
        story += _section(section, width, st)
    return story


def render_pdf(bundle: DealExportBundle) -> RenderedExport:
    fonts()
    probe = _Doc(io.BytesIO(), bundle, None)
    probe.build(_story(bundle, probe.width))
    pages = probe.page
    buf = io.BytesIO()
    doc = _Doc(buf, bundle, pages)
    doc.build(_story(bundle, doc.width))
    return RenderedExport(buf.getvalue(), "application/pdf", "pdf")
