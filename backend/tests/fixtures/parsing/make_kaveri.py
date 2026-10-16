"""Generate the parsing fixtures: the fictional 'Project Kaveri' deal pack + ground_truth.json.

Used by the parsing eval (python -m aura.evals.run --capability parsing) and, for its 22
"queries", the kav-* cases of the retrieval golden set. The committed files are the output of
this script; regenerate them (only if the corpus must change) from backend/ with

    uv run --with reportlab python tests/fixtures/parsing/make_kaveri.py tests/fixtures/parsing

It needs Windows fonts (C:/Windows/Fonts: Arial, Times, Courier...), reportlab, PIL and numpy.
Randomness is seeded, but rasterising the scanned PDFs can still differ across library
versions: re-run the parsing eval after regenerating.

Conventions (also stored in ground_truth.json):
Generate the bake-off corpus (fictional 'Project Kaveri' deal pack) + ground_truth.json.

Every document is rendered from the same element list that produces its ground truth:
elements are ("h", text, level) | ("p", text) | ("t", name, grid) | ("fn", text).
Ground-truth text = headings/paragraphs as-is, tables row by row (non-empty cells joined by
a space), in reading order. Merged cells: text in the first cell of the span, "" elsewhere.
"""

import io
import json
import math
import random
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

CONVENTIONS = 'Generate the bake-off corpus (fictional \'Project Kaveri\' deal pack) + ground_truth.json.\n\nEvery document is rendered from the same element list that produces its ground truth:\nelements are ("h", text, level) | ("p", text) | ("t", name, grid) | ("fn", text).\nGround-truth text = headings/paragraphs as-is, tables row by row (non-empty cells joined by\na space), in reading order. Merged cells: text in the first cell of the span, "" elsewhere.\n'

OUT = Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)
FONTS = "C:/Windows/Fonts/"
random.seed(7)
np.random.seed(7)

CO = "Kaveri Precision Components Private Limited"
CIN = "U29253MH2011PTC215478"
PAN = "AAFCK4821M"

PL = [["Particulars", "Note", "Year ended 31 March", ""],
      ["", "", "FY24", "FY23"],
      ["Revenue from operations", "24", "412.38", "356.91"],
      ["Other income", "25", "4.17", "3.62"],
      ["Total income", "", "416.55", "360.53"],
      ["Cost of materials consumed", "26", "231.46", "204.83"],
      ["Employee benefits expense", "27", "48.92", "42.17"],
      ["Other expenses", "28", "63.85", "57.39"],
      ["EBITDA", "", "68.15", "52.52"],
      ["Depreciation and amortisation expense", "29", "14.26", "12.88"],
      ["Finance costs", "30", "11.73", "10.95"],
      ["Exceptional items", "31", "(3.42)", "1.15"],
      ["Profit before tax", "", "42.91", "33.46"],
      ["Tax expense", "32", "10.98", "8.61"],
      ["Profit for the year", "", "31.93", "24.85"],
      ["Other comprehensive income", "", "(0.86)", "0.42"],
      ["Total comprehensive income", "", "31.07", "25.27"]]
BS = [["Particulars", "Note", "As at 31 March", ""],
      ["", "", "2024", "2023"],
      ["Property, plant and equipment", "4", "186.42", "172.09"],
      ["Capital work-in-progress", "4", "12.37", "8.64"],
      ["Inventories", "9", "74.18", "66.25"],
      ["Trade receivables", "10", "88.63", "79.40"],
      ["Cash and cash equivalents", "11", "21.35", "18.72"],
      ["Other current assets", "12", "15.06", "13.91"],
      ["Total assets", "", "398.01", "359.01"],
      ["Equity share capital", "13", "24.00", "24.00"],
      ["Other equity", "14", "162.88", "131.81"],
      ["Long-term borrowings", "15", "84.60", "92.15"],
      ["Short-term borrowings", "16", "33.15", "28.40"],
      ["Trade payables", "17", "71.46", "63.02"],
      ["Other current liabilities", "18", "21.92", "19.63"],
      ["Total equity and liabilities", "", "398.01", "359.01"]]
DEBT = [["Lender", "Facility", "Sanctioned", "Outstanding", "Rate", "Maturity"],
        ["State Bank of India", "Term loan", "60.00", "42.30", "9.10%", "Mar-2029"],
        ["HDFC Bank", "Term loan", "35.00", "24.80", "9.35%", "Sep-2028"],
        ["Axis Bank", "Cash credit", "25.00", "18.65", "9.60%", "Renewable"],
        ["ICICI Bank", "WCDL", "15.00", "14.50", "9.25%", "Jun-2024"],
        ["Bajaj Finance", "Equipment loan", "20.00", "17.50", "10.40%", "Dec-2027"],
        ["Total", "", "155.00", "117.75", "", ""]]
CAP = [["Shareholding pattern as at 31 March 2024 (fully diluted)", "", "", ""],
       ["Shareholder", "Class", "No. of shares", "% holding"],
       ["Raghunathan Family Trust", "Equity", "1,32,00,000", "55.00%"],
       ["Meera Raghunathan", "Equity", "24,00,000", "10.00%"],
       ["Deccan Growth Fund II", "CCPS Series A", "60,00,000", "25.00%"],
       ["ESOP pool", "Options", "12,00,000", "5.00%"],
       ["Others", "Equity", "12,00,000", "5.00%"],
       ["Total", "", "2,40,00,000", "100.00%"]]
TEASER = [["Metric (₹ crore)", "FY23", "FY24"],
          ["Revenue", "356.91", "412.38"],
          ["EBITDA", "52.52", "68.15"],
          ["EBITDA margin", "14.7%", "16.5%"],
          ["PAT", "24.85", "31.93"],
          ["Net debt", "—", "96.40"]]
XL_PL = [["Kaveri Precision Components – Financial model (₹ crore)", "", "", ""],
         ["Particulars", "Actual", "Projections", ""],
         ["", "FY24A", "FY25E", "FY26E"],
         ["Revenue from operations", 412.38, 468.52, 531.27],
         ["EBITDA", 68.15, 79.65, 92.43],
         ["EBITDA margin %", 16.53, 17.01, 17.39],
         ["Profit after tax", 31.93, 38.74, 46.12]]
XL_DEBT = [["Borrowings and net debt (₹ crore)", "", "", ""],
           ["Lender", "Facility", "Outstanding FY24", "Rate %"],
           ["State Bank of India", "Term loan", 42.3, 9.1],
           ["HDFC Bank", "Term loan", 24.8, 9.35],
           ["Axis Bank", "Cash credit", 18.65, 9.6],
           ["ICICI Bank", "WCDL", 14.5, 9.25],
           ["Bajaj Finance", "Equipment loan", 17.5, 10.4],
           ["Gross debt", "", 117.75, ""],
           ["Less: cash and cash equivalents", "", 21.35, ""],
           ["Net debt", "", 96.4, ""]]


def xl_str(v):
    if isinstance(v, float):
        return str(int(v)) if v.is_integer() else f"{v:.6g}"
    return str(v)


def gt_text(elements):
    out = []
    for e in elements:
        if e[0] in ("h", "p", "fn"):
            out.append(e[1])
        elif e[0] == "t":
            for row in e[2]:
                cells = [xl_str(c) for c in row if xl_str(c).strip()]
                if cells:
                    out.append(" ".join(cells))
    return "\n".join(out)


def gt_entry(elements, kind, pages, key_fields, table_fields=()):
    return {"kind": kind, "pages": pages, "text": gt_text(elements),
            "headings": [e[1] for e in elements if e[0] == "h"],
            "tables": [{"name": e[1], "grid": [[xl_str(c) for c in r] for r in e[2]]}
                       for e in elements if e[0] == "t"],
            "key_fields": key_fields, "table_fields": list(table_fields)}


GT = {}

# ---------------------------------------------------------------- 1. audited financials PDF
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, Frame, FrameBreak, PageBreak, PageTemplate,
                                Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle)

pdfmetrics.registerFont(TTFont("Arial", FONTS + "arial.ttf"))
pdfmetrics.registerFont(TTFont("ArialBd", FONTS + "arialbd.ttf"))
H1 = ParagraphStyle("h1", fontName="ArialBd", fontSize=15, leading=19, spaceAfter=6)
H2 = ParagraphStyle("h2", fontName="ArialBd", fontSize=12, leading=15, spaceBefore=8,
                    spaceAfter=4)
BODY = ParagraphStyle("b", fontName="Arial", fontSize=9.5, leading=12.5, spaceAfter=5)
SMALL = ParagraphStyle("s", fontName="Arial", fontSize=7.5, leading=9.5)


def fin_table(grid):
    data = [[Paragraph(c, ParagraphStyle("c", fontName="ArialBd" if i < 2 or r[0].startswith(
        "Total") or r[0] in ("EBITDA", "Profit before tax", "Profit for the year") else "Arial",
        fontSize=9, leading=11, alignment=0 if j == 0 else 2)) for j, c in enumerate(r)]
        for i, r in enumerate(grid)]
    t = Table(data, colWidths=[8.2 * cm, 1.5 * cm, 3.3 * cm, 3.3 * cm])
    t.setStyle(TableStyle([("SPAN", (0, 0), (0, 1)), ("SPAN", (1, 0), (1, 1)),
                           ("SPAN", (2, 0), (3, 0)), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                           ("LINEABOVE", (0, 0), (-1, 0), 0.8, colors.black),
                           ("LINEBELOW", (0, 1), (-1, 1), 0.8, colors.black),
                           ("LINEBELOW", (2, 0), (3, 0), 0.4, colors.black),
                           ("LINEBELOW", (0, -1), (-1, -1), 0.8, colors.black)]))
    return t


fin_el = [("h", CO, 1),
          ("p", f"CIN: {CIN} | PAN: {PAN} | Registered office: Plot 42, MIDC Chakan, Pune 410501"),
          ("h", "Independent Auditor's Report", 2),
          ("p", "We have audited the accompanying financial statements of Kaveri Precision "
                "Components Private Limited, which comprise the Balance Sheet as at 31 March "
                "2024 and the Statement of Profit and Loss for the year then ended. In our "
                "opinion, the financial statements give a true and fair view in conformity with "
                "the Indian Accounting Standards (Ind AS)."),
          ("h", "Statement of Profit and Loss for the year ended 31 March 2024", 2),
          ("p", "(All amounts in ₹ crore, unless otherwise stated)"),
          ("t", "pl", PL),
          ("h", "Balance Sheet as at 31 March 2024", 2),
          ("p", "(All amounts in ₹ crore, unless otherwise stated)"),
          ("t", "bs", BS),
          ("h", "Notes to the financial statements", 2),
          ("p", "Net debt as at 31 March 2024 is ₹96.40 crore (long-term borrowings of ₹84.60 "
                "crore and short-term borrowings of ₹33.15 crore, less cash and cash "
                "equivalents of ₹21.35 crore). Exceptional items of ₹3.42 crore relate to a "
                "one-time voluntary retirement scheme at the Hosur plant.")]
story = []
for e in fin_el:
    if e[0] == "h":
        if e[1].startswith("Balance Sheet"):
            story.append(PageBreak())
        story.append(Paragraph(e[1], H1 if e[2] == 1 else H2))
    elif e[0] == "p":
        story.append(Paragraph(e[1], BODY))
    else:
        story += [fin_table(e[2]), Spacer(1, 8)]
SimpleDocTemplate(str(OUT / "kaveri_audited_financials_fy24.pdf"), pagesize=A4,
                  leftMargin=2 * cm, rightMargin=2 * cm, topMargin=2 * cm,
                  bottomMargin=2 * cm, title="Audited financial statements FY24").build(story)
GT["kaveri_audited_financials_fy24.pdf"] = gt_entry(
    fin_el, "pdf_digital", 2,
    {"company_name": [CO], "cin": [CIN], "pan": [PAN], "revenue_fy24": ["412.38"],
     "ebitda_fy24": ["68.15"], "net_debt": ["96.40"]},
    [{"field": "revenue_fy24", "table": "pl", "row": "Revenue from operations", "col": "FY24",
      "value": "412.38"},
     {"field": "ebitda_fy24", "table": "pl", "row": "EBITDA", "col": "FY24", "value": "68.15"},
     {"field": "exceptional_fy24", "table": "pl", "row": "Exceptional items", "col": "FY24",
      "value": "(3.42)"},
     {"field": "receivables_2024", "table": "bs", "row": "Trade receivables", "col": "2024",
      "value": "88.63"}])

# ---------------------------------------------------------------- 2. two-column term sheet
TS = [("Issuer", f"{CO} (the \"Issuer\"), a private company incorporated in India with CIN "
                 f"{CIN} and PAN {PAN}."),
      ("Instrument", "Senior secured, rated, listed, redeemable non-convertible debentures "
                     "(\"NCDs\") of face value ₹1,00,000 each, issued on a private placement "
                     "basis.<super>1</super>"),
      ("Ticket size", "INR 150 crore (Rupees One Hundred and Fifty Crore only), in one or more "
                      "tranches."),
      ("Tenor", "60 months from the Deemed Date of Allotment, with a bullet redemption at "
                "par."),
      ("Coupon", "11.25% per annum, payable quarterly, on an actual/365 day-count "
                 "basis.<super>2</super>"),
      ("Security", "First ranking exclusive charge over the movable fixed assets of the Hosur "
                   "and Chakan plants, with a minimum security cover of 1.25 times the "
                   "outstanding amount."),
      ("Financial covenants", "Minimum DSCR of 1.25x and Net debt to EBITDA not exceeding 2.5x, "
                              "tested semi-annually on the audited or reviewed financial "
                              "statements."),
      ("Use of proceeds", "Refinancing of existing term loans, capital expenditure on the new "
                          "machining line and general corporate purposes not exceeding 25% of "
                          "the issue size."),
      ("Conditions precedent", "Execution of the debenture trust deed, creation of security, "
                               "credit rating of at least A- and receipt of the board and "
                               "shareholder resolutions."),
      ("Governing law and jurisdiction", "The NCDs shall be governed by the laws of India. The "
                                         "courts and tribunals at Mumbai shall have exclusive "
                                         "jurisdiction.<super>3</super>"),
      ("Fees", "Arranger fee of 0.75% of the issue size, payable on the Deemed Date of "
               "Allotment.")]
FOOT = ["1 The NCDs will be listed on the wholesale debt market segment of BSE Limited.",
        "2 Step-up of 0.50% per annum for every notch of rating downgrade below A-.",
        "3 Subject to the arbitration clause in the debenture trust deed."]
ts_el = [("h", "Indicative Term Sheet – Project Kaveri", 1),
         ("p", "Strictly private and confidential. For discussion purposes only; not an offer.")]
for i, (h, body) in enumerate(TS, 1):
    ts_el += [("h", f"{i}. {h}", 2), ("p", body.replace("<super>", "").replace("</super>", ""))]
ts_el += [("fn", f) for f in FOOT]
TS_H1 = ParagraphStyle("t1", fontName="ArialBd", fontSize=16, leading=20, spaceAfter=4)
TS_H2 = ParagraphStyle("t2", fontName="ArialBd", fontSize=10.5, leading=13, spaceBefore=6,
                       spaceAfter=2)
TS_B = ParagraphStyle("tb", fontName="Arial", fontSize=9, leading=11.5, alignment=4)
W, H = A4
M = 1.8 * cm
gap = 0.8 * cm
colw = (W - 2 * M - gap) / 2
foot_h = 2.4 * cm


def ts_page(canv, doc):
    canv.setLineWidth(0.5)
    canv.line(M, M + foot_h - 4, M + 6 * cm, M + foot_h - 4)
    y = M + foot_h - 16
    for f in FOOT:
        canv.setFont("Arial", 7.5)
        num, rest = f.split(" ", 1)
        canv.setFont("Arial", 6)
        canv.drawString(M, y + 3, num)
        canv.setFont("Arial", 7.5)
        canv.drawString(M + 6, y, rest)
        y -= 11


title_h = 2.2 * cm
frames = [Frame(M, H - M - title_h, W - 2 * M, title_h, id="title"),
          Frame(M, M + foot_h, colw, H - 2 * M - title_h - foot_h, id="c1"),
          Frame(M + colw + gap, M + foot_h, colw, H - 2 * M - title_h - foot_h, id="c2")]
doc = BaseDocTemplate(str(OUT / "kaveri_ncd_term_sheet.pdf"), pagesize=A4,
                      title="Indicative term sheet")
doc.addPageTemplates([PageTemplate(id="two", frames=frames, onPage=ts_page)])
story = [Paragraph(ts_el[0][1], TS_H1), Paragraph(ts_el[1][1], TS_B), FrameBreak()]
for i, (h, body) in enumerate(TS, 1):
    story += [Paragraph(f"{i}. {h}", TS_H2), Paragraph(body, TS_B)]
    if i == 6:
        story.append(FrameBreak())
doc.build(story)
GT["kaveri_ncd_term_sheet.pdf"] = gt_entry(
    ts_el, "pdf_digital", 1,
    {"company_name": [CO], "cin": [CIN], "pan": [PAN], "ticket_size": ["INR 150 crore"],
     "tenor": ["60 months"], "coupon": ["11.25% per annum"],
     "security": ["First ranking exclusive charge"], "governing_law": ["laws of India"]})

# ---------------------------------------------------------------- scanned-page helpers
DPI = 200
PW, PH = int(8.27 * DPI), int(11.69 * DPI)


def font(name, pt):
    return ImageFont.truetype(FONTS + name, int(pt * DPI / 72))


def scan_finish(img, angle, noise=14, quality=62):
    img = img.rotate(angle, resample=Image.BICUBIC, expand=False, fillcolor="white")
    a = np.asarray(img).astype(np.int16)
    a = a + np.random.normal(0, noise, a.shape).astype(np.int16)
    speck = np.random.random(a.shape[:2]) < 0.0015
    a[speck] = 40
    a = np.clip(a, 0, 255).astype(np.uint8)
    img = Image.fromarray(a)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality)
    return buf.getvalue()


def image_pdf(path, jpegs):
    import fitz
    d = fitz.open()
    for jp in jpegs:
        p = d.new_page(width=595.3, height=841.9)
        p.insert_image(p.rect, stream=jp)
    d.save(str(path))


def draw_wrapped(dr, x, y, text, f, maxw, lead):
    words, line = text.split(), ""
    for w in words:
        t = (line + " " + w).strip()
        if dr.textlength(t, font=f) > maxw:
            dr.text((x, y), line, font=f, fill=0)
            y += lead
            line = w
        else:
            line = t
    if line:
        dr.text((x, y), line, font=f, fill=0)
        y += lead
    return y


# ---------------------------------------------------------------- 3. scanned debt schedule
sd_el = [("h", CO, 1), ("h", "Schedule of Borrowings as at 31 March 2024", 2),
         ("p", "(All amounts in ₹ crore)"),
         ("t", "debt", DEBT),
         ("p", "Net debt as at 31 March 2024 is ₹96.40 crore after deducting cash and cash "
               "equivalents of ₹21.35 crore from gross borrowings of ₹117.75 crore."),
         ("p", "Certified by the Chief Financial Officer on the basis of lender confirmations.")]
img = Image.new("L", (PW, PH), 255)
dr = ImageDraw.Draw(img)
x0, y = 150, 170
dr.text((x0, y), CO, font=font("arialbd.ttf", 15), fill=0); y += 80
dr.text((x0, y), sd_el[1][1], font=font("arialbd.ttf", 12), fill=0); y += 60
dr.text((x0, y), sd_el[2][1], font=font("arial.ttf", 10), fill=0); y += 70
cols = [120, 450, 730, 920, 1130, 1270, 1534]
rh = 62
f10, f10b = font("arial.ttf", 10), font("arialbd.ttf", 10)
for ri, row in enumerate(DEBT):
    dr.line((cols[0], y, cols[-1], y), fill=0, width=3 if ri in (0, 1) else 2)
    for ci, c in enumerate(row):
        fnt = f10b if ri == 0 or row[0] == "Total" else f10
        if ci >= 2 and ci <= 4:
            tw = dr.textlength(c, font=fnt)
            dr.text((cols[ci + 1] - 25 - tw, y + 15), c, font=fnt, fill=0)
        else:
            dr.text((cols[ci] + 15, y + 15), c, font=fnt, fill=0)
    y += rh
dr.line((cols[0], y, cols[-1], y), fill=0, width=3)
for c in cols:
    dr.line((c, y - rh * len(DEBT), c, y), fill=0, width=2)
y += 60
for e in sd_el[4:]:
    y = draw_wrapped(dr, x0, y, e[1], f10, PW - 2 * x0, 44) + 20
image_pdf(OUT / "kaveri_borrowings_schedule_scanned.pdf", [scan_finish(img, 1.2)])
GT["kaveri_borrowings_schedule_scanned.pdf"] = gt_entry(
    sd_el, "pdf_scanned", 1, {"company_name": [CO], "net_debt": ["96.40"]},
    [{"field": "sbi_outstanding", "table": "debt", "row": "State Bank of India",
      "col": "Outstanding", "value": "42.30"},
     {"field": "hdfc_rate", "table": "debt", "row": "HDFC Bank", "col": "Rate",
      "value": "9.35%"},
     {"field": "total_outstanding", "table": "debt", "row": "Total", "col": "Outstanding",
      "value": "117.75"}])

# ---------------------------------------------------------------- 4. scanned board resolution
HAND = {"date": "14/06/2024", "place": "Pune", "name": "Meera Raghunathan", "din": "07345128"}
br_el = [("h", CO, 1),
         ("p", f"CIN: {CIN} PAN: {PAN}"),
         ("h", "Certified True Copy of the Resolution passed by the Board of Directors", 2),
         ("p", "RESOLVED THAT pursuant to Section 42 and Section 71 of the Companies Act, 2013, "
               "the consent of the Board be and is hereby accorded to borrow up to INR 150 "
               "crore by issue of secured non-convertible debentures on a private placement "
               "basis."),
         ("p", "RESOLVED FURTHER THAT any Director of the Company be and is hereby authorised "
               "to sign and execute the debenture trust deed and all related documents."),
         ("p", f"Date: {HAND['date']}"), ("p", f"Place: {HAND['place']}"),
         ("p", f"Name of authorised signatory: {HAND['name']}"),
         ("p", f"DIN: {HAND['din']}")]
img = Image.new("RGB", (PW, PH), "white")
dr = ImageDraw.Draw(img)
y = 170
dr.text((x0, y), CO, font=font("arialbd.ttf", 15), fill=0); y += 75
dr.text((x0, y), br_el[1][1], font=font("arial.ttf", 10), fill=0); y += 90
dr.text((x0, y), br_el[2][1], font=font("arialbd.ttf", 12), fill=0); y += 90
f105 = font("arial.ttf", 10.5)
for e in br_el[3:5]:
    y = draw_wrapped(dr, x0, y, e[1], f105, PW - 2 * x0, 46) + 30
y += 40
hand = font("Inkfree.ttf", 16)
ink = (20, 40, 140)
for label, key in (("Date:", "date"), ("Place:", "place"),
                   ("Name of authorised signatory:", "name"), ("DIN:", "din")):
    dr.text((x0, y), label, font=f105, fill=0)
    lx = x0 + dr.textlength(label, font=f105) + 25
    dr.line((lx, y + 50, lx + 700, y + 50), fill=(90, 90, 90), width=2)
    dr.text((lx + 10, y - 12), HAND[key], font=hand, fill=ink)
    y += 110
# signature squiggle
pts = [(x0 + 900 + t * 6, y - 330 + 40 * math.sin(t / 6) + 15 * math.sin(t / 1.7))
       for t in range(90)]
dr.line(pts, fill=ink, width=5)
# round stamp overlay
st = Image.new("RGBA", (520, 520), (0, 0, 0, 0))
sd = ImageDraw.Draw(st)
red = (200, 30, 40, 170)
sd.ellipse((10, 10, 510, 510), outline=red, width=10)
sd.ellipse((60, 60, 460, 460), outline=red, width=5)
sf = font("arialbd.ttf", 10)
for i, line in enumerate(["KAVERI PRECISION", "COMPONENTS", "PVT. LTD.", "* PUNE *"]):
    tw = sd.textlength(line, font=sf)
    sd.text((260 - tw / 2, 150 + i * 60), line, font=sf, fill=red)
st = st.rotate(-14, resample=Image.BICUBIC)
img.paste(st, (x0 + 700, y - 560), st)
image_pdf(OUT / "kaveri_board_resolution_scanned.pdf", [scan_finish(img, -0.8, noise=10)])
GT["kaveri_board_resolution_scanned.pdf"] = gt_entry(
    br_el, "pdf_scanned", 1,
    {"company_name": [CO], "cin": [CIN], "pan": [PAN], "ticket_size": ["INR 150 crore"],
     "signatory_handwritten": [HAND["name"]], "date_handwritten": [HAND["date"]],
     "din_handwritten": [HAND["din"]]})

# ---------------------------------------------------------------- 5. DOCX IM with cap table
import docx
from docx.shared import Pt

im_el = [("h", "Information Memorandum – Project Kaveri", 1),
         ("p", "Prepared for prospective investors in the proposed NCD issue of Kaveri "
               "Precision Components Private Limited."),
         ("h", "Company overview", 2),
         ("h", "History", 3),
         ("p", f"{CO} (CIN {CIN}) was incorporated in 2011 and manufactures precision "
               "machined components for two-wheeler and tractor OEMs from plants at Chakan "
               "and Hosur."),
         ("h", "Operations", 3),
         ("p", "The Company operates 146 CNC machining centres and employs 1,240 people. "
               "Its top five customers contributed 61% of FY24 revenue."),
         ("h", "Shareholding", 2),
         ("p", "The cap table below is on a fully diluted basis, including the ESOP pool "
               "and the Series A compulsorily convertible preference shares."),
         ("t", "cap", CAP),
         ("h", "Financial highlights", 2),
         ("p", "In FY24 revenue from operations was ₹412.38 crore and EBITDA was ₹68.15 crore "
               "(16.5% margin). Net debt as at 31 March 2024 was ₹96.40 crore."),
         ("h", "Proposed transaction", 2),
         ("h", "Use of proceeds", 3),
         ("p", "The INR 150 crore NCD issue will refinance existing term loans and fund the "
               "new machining line at Hosur.")]
d = docx.Document()
for e in im_el:
    if e[0] == "h":
        d.add_heading(e[1], level=e[2])
    elif e[0] == "p":
        d.add_paragraph(e[1])
    else:
        g = e[2]
        t = d.add_table(rows=len(g), cols=4)
        t.style = "Table Grid"
        for i, r in enumerate(g):
            for j, c in enumerate(r):
                if c:
                    t.cell(i, j).text = c
        t.cell(0, 0).merge(t.cell(0, 3))
        t.cell(0, 0).text = g[0][0]
d.save(OUT / "kaveri_information_memorandum.docx")
GT["kaveri_information_memorandum.docx"] = gt_entry(
    im_el, "docx", None,
    {"company_name": [CO], "cin": [CIN], "revenue_fy24": ["412.38"], "ebitda_fy24": ["68.15"],
     "net_debt": ["96.40"], "ticket_size": ["INR 150 crore"]},
    [{"field": "deccan_holding", "table": "cap", "row": "Deccan Growth Fund II",
      "col": "% holding", "value": "25.00%"},
     {"field": "esop_shares", "table": "cap", "row": "ESOP pool", "col": "No. of shares",
      "value": "12,00,000"}])

# ---------------------------------------------------------------- 6. XLSX model
import openpyxl
from openpyxl.styles import Font

wb = openpyxl.Workbook()
ws = wb.active
ws.title = "P&L"
for r in XL_PL:
    ws.append([c if c != "" else None for c in r])
ws.merge_cells("A1:D1")
ws.merge_cells("C2:D2")
ws["A1"].font = Font(bold=True)
for row in ws.iter_rows(min_row=4):
    for c in row[1:]:
        c.number_format = "#,##0.00"
ws2 = wb.create_sheet("Debt")
for r in XL_DEBT:
    ws2.append([c if c != "" else None for c in r])
ws2.merge_cells("A1:D1")
for row in ws2.iter_rows(min_row=3):
    for c in row[2:]:
        c.number_format = "#,##0.00"
wb.save(OUT / "kaveri_financial_model.xlsx")
xl_el = [("h", "P&L", 1), ("t", "xl_pl", XL_PL), ("h", "Debt", 1), ("t", "xl_debt", XL_DEBT)]
GT["kaveri_financial_model.xlsx"] = gt_entry(
    xl_el, "xlsx", None,
    {"revenue_fy24": ["412.38"], "ebitda_fy24": ["68.15"], "net_debt": ["96.4", "96.40"]},
    [{"field": "ebitda_fy26", "table": "xl_pl", "row": "EBITDA", "col": "FY26E",
      "value": "92.43"},
     {"field": "net_debt", "table": "xl_debt", "row": "Net debt", "col": "Outstanding FY24",
      "value": "96.4"}])

# ---------------------------------------------------------------- 7. PPTX teaser
from pptx import Presentation
from pptx.util import Inches, Pt as PPt

prs = Presentation()
s = prs.slides.add_slide(prs.slide_layouts[0])
s.shapes.title.text = "Project Kaveri – Investment Teaser"
s.placeholders[1].text = "Strictly private and confidential"
hl = ["Leading precision components supplier to two-wheeler and tractor OEMs",
      "Revenue of ₹412.38 crore in FY24, up 15.5% year on year",
      "EBITDA of ₹68.15 crore with a 16.5% margin",
      "Net debt to EBITDA of 1.4x as at 31 March 2024"]
s = prs.slides.add_slide(prs.slide_layouts[1])
s.shapes.title.text = "Investment highlights"
s.placeholders[1].text = "\n".join(hl)
s.notes_slide.notes_text_frame.text = ("Emphasise the 16.5% EBITDA margin and the INR 150 crore "
                                       "NCD ask.")
s = prs.slides.add_slide(prs.slide_layouts[5])
s.shapes.title.text = "Key financials"
tb = s.shapes.add_table(len(TEASER), 3, Inches(1), Inches(1.8), Inches(8), Inches(3)).table
for i, r in enumerate(TEASER):
    for j, c in enumerate(r):
        tb.cell(i, j).text = c
tx = ["Ticket size: INR 150 crore of senior secured NCDs",
      "Tenor: 60 months; coupon: 11.25% per annum payable quarterly",
      "Security: first ranking exclusive charge over movable fixed assets",
      "Governing law: laws of India"]
s = prs.slides.add_slide(prs.slide_layouts[1])
s.shapes.title.text = "Transaction overview"
s.placeholders[1].text = "\n".join(tx)
s.notes_slide.notes_text_frame.text = "Investors have asked about the step-up on rating downgrade."
prs.save(OUT / "kaveri_teaser.pptx")
pp_el = [("h", "Project Kaveri – Investment Teaser", 1), ("p", "Strictly private and confidential"),
         ("h", "Investment highlights", 1)] + [("p", x) for x in hl] + [
    ("p", "Emphasise the 16.5% EBITDA margin and the INR 150 crore NCD ask."),
    ("h", "Key financials", 1), ("t", "teaser", TEASER),
    ("h", "Transaction overview", 1)] + [("p", x) for x in tx] + [
    ("p", "Investors have asked about the step-up on rating downgrade.")]
GT["kaveri_teaser.pptx"] = gt_entry(
    pp_el, "pptx", 4,
    {"revenue_fy24": ["412.38"], "ebitda_fy24": ["68.15"], "net_debt": ["96.40"],
     "ticket_size": ["INR 150 crore"], "tenor": ["60 months"], "coupon": ["11.25% per annum"],
     "security": ["first ranking exclusive charge"], "governing_law": ["laws of India"]},
    [{"field": "ebitda_fy24", "table": "teaser", "row": "EBITDA", "col": "FY24",
      "value": "68.15"}])

# ---------------------------------------------------------------- queries
F = {"fin": "kaveri_audited_financials_fy24.pdf", "ts": "kaveri_ncd_term_sheet.pdf",
     "sd": "kaveri_borrowings_schedule_scanned.pdf", "br": "kaveri_board_resolution_scanned.pdf",
     "im": "kaveri_information_memorandum.docx", "xl": "kaveri_financial_model.xlsx",
     "pp": "kaveri_teaser.pptx"}


def q(i, query, *exp, note=""):
    return {"id": f"kav-{i:02d}", "query": query,
            "expected": [{"filename": F[f], "contains": c} for f, c in exp], "note": note}


QUERIES = [
    q(1, "What was revenue from operations in FY24?", ("fin", "412.38"), ("xl", "412.38"),
      ("im", "412.38"), ("pp", "412.38")),
    q(2, "exceptional items charge in the statement of profit and loss", ("fin", "Exceptional")),
    q(3, "trade receivables as at 31 March 2024", ("fin", "88.63")),
    q(4, "net debt", ("fin", "96.40"), ("xl", "96.4"), ("im", "96.40"), ("pp", "96.40"),
      ("sd", "96.40")),
    q(5, "coupon rate on the debentures", ("ts", "11.25%"), ("pp", "11.25%")),
    q(6, "tenor of the NCD", ("ts", "60 months"), ("pp", "60 months")),
    q(7, "security and charge over assets", ("ts", "exclusive charge"),
      ("pp", "exclusive charge")),
    q(8, "governing law and jurisdiction", ("ts", "laws of India"), ("pp", "laws of India")),
    q(9, "financial covenants DSCR", ("ts", "DSCR")),
    q(10, "State Bank of India term loan outstanding", ("sd", "42.30"), ("xl", "State Bank"),
      note="scanned table (OCR) or model"),
    q(11, "HDFC Bank interest rate", ("sd", "9.35"), ("xl", "HDFC"),
      note="scanned table (OCR) or model"),
    q(12, "board resolution authorising borrowing by NCD issue", ("br", "RESOLVED"),
      note="scanned, stamp overlay"),
    q(13, "who is the authorised signatory of the resolution", ("br", "Meera"),
      note="handwritten field on a scan"),
    q(14, "shareholding of Deccan Growth Fund", ("im", "Deccan Growth")),
    q(15, "ESOP pool size", ("im", "ESOP")),
    q(16, "EBITDA projection for FY26", ("xl", "92.43")),
    q(17, "investment highlights", ("pp", "highlights")),
    q(18, "what should the presenter emphasise", ("pp", "Emphasise"),
      note="speaker notes"),
    q(19, "use of proceeds of the issue", ("im", "proceeds"), ("ts", "proceeds")),
    q(20, "conditions precedent to the issue", ("ts", "Conditions precedent")),
    q(21, "Company PAN number", ("ts", PAN), ("fin", PAN), ("br", PAN)),
    q(22, "lender confirmations certified by the CFO", ("sd", "Chief Financial Officer"),
      note="scanned body text"),
]

json.dump({"company": CO, "documents": GT, "queries": QUERIES,
           "conventions": CONVENTIONS}, open(OUT / "ground_truth.json", "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
print("ok", sorted(GT))
