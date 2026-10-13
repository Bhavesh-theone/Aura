"""Machine and spreadsheet renderings: JSON, CSV (deals list), ZIP of per-section CSVs, XLSX.

JSON and CSV carry raw values (rupees as integers, ISO 8601 UTC timestamps). XLSX cells are
typed: rupees are numbers with an Indian-grouping ₹ format, timestamps are real dates."""
import csv
import io
import json
import zipfile
from datetime import timezone

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from aura.core.domain.export import DealExportBundle, ExportTable
from aura.exports.common import RenderedExport, parse_iso

# Excel has no lakh/crore grouping; conditional sections give 1,23,45,678 for up to 99 crore
# and keep grouping (in thousands of crore) above it.
INR_FORMAT = ('[>=10000000]"₹"##\\,##\\,##\\,##0;[>=100000]"₹"##\\,##\\,##0;"₹"#,##0')
DATETIME_FORMAT = "dd mmm yyyy hh:mm"
DATE_FORMAT = "dd mmm yyyy"
XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


# --------------------------------------------------------------------------- JSON

def render_json(bundle: DealExportBundle) -> RenderedExport:
    body = json.dumps(bundle.to_json_dict(), ensure_ascii=False, indent=2, sort_keys=False,
                      default=str)
    return RenderedExport(body.encode("utf-8"), "application/json", "json")


# --------------------------------------------------------------------------- CSV

def _csv_value(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return value


def table_csv(table: ExportTable) -> bytes:
    """UTF-8 with a BOM (so Excel reads ₹ and Indian names right), header = column keys."""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\r\n")
    writer.writerow([c.key for c in table.columns])
    for row in table.rows:
        writer.writerow([_csv_value(row.get(c.key)) for c in table.columns])
    return ("﻿" + buf.getvalue()).encode("utf-8")


def render_csv_table(table: ExportTable) -> RenderedExport:
    return RenderedExport(table_csv(table), "text/csv; charset=utf-8", "csv")


def render_zip(bundle: DealExportBundle) -> RenderedExport:
    """One CSV per table (NN_section__table.csv), the facts of every section, the full JSON
    bundle and a manifest."""
    buf = io.BytesIO()
    files = []
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        n = 0
        for section in bundle.sections:
            for table in section.tables:
                n += 1
                name = f"{n:02d}_{section.key}__{table.key}.csv"
                z.writestr(name, table_csv(table))
                files.append({"file": name, "section": section.key, "table": table.key,
                              "rows": len(table.rows)})
        facts = io.StringIO()
        w = csv.writer(facts, lineterminator="\r\n")
        w.writerow(["section", "label", "value"])
        for section in bundle.sections:
            for label, value in section.facts:
                w.writerow([section.key, label, value])
        z.writestr("00_facts.csv", ("﻿" + facts.getvalue()).encode("utf-8"))
        z.writestr("deal.json", render_json(bundle).content)
        manifest = {"schema_version": bundle.schema_version, "deal": bundle.deal,
                    "generated_at": bundle.generated_at, "generated_by": bundle.generated_by,
                    "sections": bundle.section_keys, "upsi": bundle.upsi,
                    "files": [{"file": "00_facts.csv"}, *files, {"file": "deal.json"}]}
        z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    return RenderedExport(buf.getvalue(), "application/zip", "zip")


# --------------------------------------------------------------------------- XLSX

_HEAD_FILL = PatternFill("solid", fgColor="F4F3EF")
_HEAD_FONT = Font(bold=True, color="14171A")
_TITLE_FONT = Font(bold=True, size=13)
_MUTED = Font(color="676E75", size=9)


def _xl_value(value, col_type: str):
    if value is None or value == "":
        return None
    if col_type in ("datetime", "date"):
        dt = parse_iso(value)
        if dt is None:
            return str(value)
        naive = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return naive.date() if col_type == "date" else naive
    if col_type in ("inr", "int") and isinstance(value, (int, float)):
        return int(value)
    if col_type in ("float", "pct") and isinstance(value, (int, float)):
        return float(value)
    if col_type == "bool":
        return bool(value)
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return value


def _sheet_title(text: str, used: set[str]) -> str:
    base = "".join(ch for ch in text if ch not in '[]:*?/\\')[:31] or "Sheet"
    title, i = base, 2
    while title.lower() in used:
        suffix = f" {i}"
        title, i = base[:31 - len(suffix)] + suffix, i + 1
    used.add(title.lower())
    return title


def _write_table(ws, table: ExportTable, start_row: int, freeze: bool) -> int:
    """Write a table from start_row; returns the next free row."""
    r = start_row
    ws.cell(row=r, column=1, value=table.title).font = Font(bold=True, size=11)
    r += 1
    if table.note:
        ws.cell(row=r, column=1, value=table.note).font = _MUTED
        r += 1
    header = r
    for i, col in enumerate(table.columns, 1):
        c = ws.cell(row=header, column=i, value=col.label)
        c.font, c.fill = _HEAD_FONT, _HEAD_FILL
        c.alignment = Alignment(horizontal="right" if col.type in ("inr", "int", "float", "pct")
                                else "left", vertical="center")
    for row in table.rows:
        r += 1
        for i, col in enumerate(table.columns, 1):
            cell = ws.cell(row=r, column=i, value=_xl_value(row.get(col.key), col.type))
            if col.type == "inr":
                cell.number_format = INR_FORMAT
            elif col.type == "int":
                cell.number_format = "#,##0"
            elif col.type == "float":
                cell.number_format = "#,##0.00"
            elif col.type == "pct":
                cell.number_format = "0%"
            elif col.type == "datetime":
                cell.number_format = DATETIME_FORMAT
            elif col.type == "date":
                cell.number_format = DATE_FORMAT
            elif col.type == "text" and isinstance(cell.value, str) and len(cell.value) > 60:
                cell.alignment = Alignment(wrap_text=True, vertical="top")
    last = max(r, header)
    if table.rows:
        ws.auto_filter.ref = f"A{header}:{get_column_letter(len(table.columns))}{last}"
    if freeze:
        ws.freeze_panes = ws.cell(row=header + 1, column=1)
    for i, col in enumerate(table.columns, 1):
        letter = get_column_letter(i)
        current = ws.column_dimensions[letter].width or 0
        want = {"inr": 16, "datetime": 18, "date": 13, "bool": 10, "int": 10, "pct": 11,
                "float": 12}.get(col.type, min(60, max(12, int(14 * col.width))))
        ws.column_dimensions[letter].width = max(current, want, len(col.label) + 3)
    if table.truncated:
        last += 1
        ws.cell(row=last, column=1, value="Truncated: more rows exist than an export "
                                          "carries.").font = _MUTED
    return last + 2


def render_xlsx(bundle: DealExportBundle) -> RenderedExport:
    """A summary sheet, then one sheet per section. A sheet with exactly one table gets a
    frozen header row and an autofilter on it; extra tables follow below."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    used = {"summary"}
    d = bundle.deal
    ws["A1"] = f"{d['external_id']} · {d['name']}"
    ws["A1"].font = _TITLE_FONT
    ws["A2"] = (f"Generated {bundle.generated_at} by {bundle.generated_by} "
                f"({bundle.generated_by_role}). Confidential"
                + (" — contains UPSI." if bundle.upsi else "."))
    ws["A2"].font = _MUTED
    r = 4
    for section in bundle.sections:
        if not section.facts:
            continue
        ws.cell(row=r, column=1, value=section.title).font = Font(bold=True)
        r += 1
        for label, value in section.facts:
            ws.cell(row=r, column=1, value=label).font = Font(color="4A5158")
            ws.cell(row=r, column=2, value=value)
            r += 1
        r += 1
    ws.column_dimensions["A"].width = 26
    ws.column_dimensions["B"].width = 70
    for section in bundle.sections:
        if not section.tables:
            continue
        sheet = wb.create_sheet(_sheet_title(section.title, used))
        sheet.sheet_properties.tabColor = "1F4FD8"
        row = 1
        single = len(section.tables) == 1
        for table in section.tables:
            row = _write_table(sheet, table, row, freeze=single)
    wb.properties.title = f"{d['external_id']} {d['name']}"
    wb.properties.creator = "Aura"
    out = io.BytesIO()
    wb.save(out)
    return RenderedExport(out.getvalue(), XLSX_MEDIA, "xlsx")


def render_list_xlsx(table: ExportTable, generated_at: str, generated_by: str) -> RenderedExport:
    wb = Workbook()
    ws = wb.active
    ws.title = "Deals"
    _write_table(ws, table, 1, freeze=True)
    ws.cell(row=len(table.rows) + 4, column=1,
            value=f"Generated {generated_at} by {generated_by}. Confidential.").font = _MUTED
    wb.properties.creator = "Aura"
    out = io.BytesIO()
    wb.save(out)
    return RenderedExport(out.getvalue(), XLSX_MEDIA, "xlsx")
