"""Build the ingestion fixture deal pack: "Project Nilgiri", the (fictional) acquisition of
Kaveri Agro Foods Private Limited by Deccan Consumer Holdings. Every entity, person and figure
is invented.

    uv run python tests/fixtures/ingest/make_fixtures.py      # (re)writes the files here

The files are generated deterministically and committed, so the tests and the retrieval
golden set (backend/evals/golden/retrieval.jsonl) read exactly these bytes.
"""
import io
import sys
from email.message import EmailMessage
from pathlib import Path

HERE = Path(__file__).resolve().parent

IM_PAGE_1 = [
    "Project Nilgiri - Information Memorandum",
    "Strictly private and confidential. Prepared for Deccan Consumer Holdings Limited.",
    "Company overview",
    "Kaveri Agro Foods Private Limited (CIN U15400TN2009PTC071234) is a Coimbatore-based "
    "maker of packaged millet snacks, ready-to-cook batters and spice blends. It runs "
    "manufacturing plants in Tamil Nadu and Karnataka and sells through modern trade, "
    "general trade and quick-commerce channels.",
    "Transaction",
    "The promoters, the Raghavan family, propose to sell a 76 percent stake to Deccan "
    "Consumer Holdings Limited. Saffron Growth Fund II will exit fully.",
]
IM_PAGE_2 = [
    "Financial highlights",
    "Revenue from operations grew from INR 410 crore in FY23 to INR 552 crore in FY25, a "
    "16 percent CAGR. EBITDA margin improved to 14.2 percent in FY25 on lower millet "
    "procurement costs and a richer product mix.",
    "Working capital",
    "Net working capital days rose to 74 days because of longer credit terms extended to "
    "modern trade customers. Inventory of finished goods is held at three regional depots.",
]
# Page 3 is an image only (a scanned annexure): its text is found only by OCR.
IM_PAGE_3_SCAN = [
    "Annexure C - Pending litigation",
    "GST show cause notice dated 14 March 2025",
    "issued by DGGI Chennai Zonal Unit demanding",
    "INR 4.2 crore of input tax credit plus interest.",
    "The company has filed a reply and disputes the demand.",
]

SPA_SECTIONS = [
    ("Share Purchase Agreement (draft for discussion)", None),
    ("1. Definitions", "Business Day means a day on which scheduled banks are open in Chennai "
     "and Mumbai. Completion means completion of the sale and purchase of the Sale Shares."),
    ("2. Purchase price", "The purchase price for the Sale Shares is INR 312 crore on a cash "
     "free, debt free basis, subject to a normalised working capital adjustment. Ten percent "
     "of the purchase price shall be deposited in an escrow account with Axis Trustee "
     "Services for eighteen months."),
    ("3. Conditions precedent", "Completion is conditional on approval of the Competition "
     "Commission of India (CCI approval) under Section 5 and Section 6 of the Competition "
     "Act, 2002, receipt of the no-objection certificate from the lenders, and a valuation "
     "certificate under the FEMA pricing guidelines."),
    ("4. Indemnities", "The sellers shall indemnify the purchaser for pre-completion tax "
     "liabilities, including the pending GST demand. The tax indemnity is capped at twenty "
     "percent of the purchase price and survives for seven years."),
    ("5. Non-compete", "Each promoter undertakes not to compete with the business in India "
     "for a non-compete period of three years from Completion."),
]
SPA_TRANCHES = [["Tranche", "Timing", "Amount (INR crore)"],
                ["First", "At Completion", "280.8"],
                ["Escrow release", "18 months after Completion", "31.2"]]

PNL = [["Particulars (INR crore)", "FY23", "FY24", "FY25"],
       ["Revenue from operations", 410, 486, 552],
       ["Gross margin", 131.2, 160.4, 187.7],
       ["EBITDA", 49.2, 63.2, 78.4],
       ["Profit after tax", 21.5, 29.8, 38.1]]
DEBT = [["Lender", "Facility", "Outstanding 31 Mar 2025 (INR crore)", "Rate"],
        ["State Bank of India", "Term loan", 85, "9.1%"],
        ["ICICI Bank", "Working capital", 42.5, "MCLR + 1.2%"],
        ["Promoter loan", "Unsecured", 6, "nil"]]
CAP_TABLE = [["Shareholder", "Shares", "Holding"],
             ["Raghavan family (promoters)", 6_200_000, "62%"],
             ["Saffron Growth Fund II", 2_400_000, "24%"],
             ["Employee stock option trust", 400_000, "4%"],
             ["Angel investors", 1_000_000, "10%"]]

SLIDES = [
    ("Company snapshot", ["Founded 2009 in Coimbatore", "12 manufacturing plants across "
                          "Tamil Nadu and Karnataka", "1,850 employees"], None,
     "Mention that two plants are leased from promoter entities."),
    ("Customers and channels", ["Largest customer DesiMart accounts for 38% of revenue "
                                "(customer concentration)", "Quick commerce grew 3x in FY25"],
     [["Channel", "FY25 share"], ["Modern trade", "46%"], ["General trade", "31%"],
      ["Quick commerce", "15%"], ["Exports", "8%"]], None),
    ("Growth plan", ["New millet noodles line in FY26", "Capex of INR 60 crore over two "
                     "years"], None,
     "Export revenue is recognised on dispatch from the factory, not on delivery; the "
     "auditors have asked for a change in revenue recognition."),
]

EMAIL_BODY = """Dear Deal Team,

Please find below the key red flags from our financial due diligence on Kaveri Agro Foods.

1. Related party transactions: the company paid INR 18 crore in FY25 to Kaveri Logistics LLP,
a promoter entity, for freight. Rates are above market and there is no board approval on file.

2. Working capital: debtor days have increased; we recommend a normalised working capital
peg of INR 96 crore in the SPA.

3. The GST show cause notice is not provided for in the books.

The diligence tracker is attached.

Regards,
Meera Iyer
Partner, Iyer Sundaram & Co (financial due diligence)
"""
TRACKER_CSV = (
    "Item,Workstream,Status,Owner\n"
    "Environmental clearance for Hosur plant,Legal,Open - renewal application pending with "
    "TNPCB,Mehta & Rao Associates\n"
    "FSSAI licences for all plants,Regulatory,Closed,Mehta & Rao Associates\n"
    "Related party transactions review,Financial,Open,Iyer Sundaram & Co\n"
    "Trademark assignment of the Kaveri brand,Legal,In progress,Mehta & Rao Associates\n")

BOARD_MINUTES = """# Minutes of the meeting of the Board of Directors

Kaveri Agro Foods Private Limited, held at Coimbatore on 2 June 2025.

## Present

S. Raghavan (Chairman), Lakshmi Raghavan, Arjun Menon (nominee of Saffron Growth Fund II).

## Approval of the proposed acquisition

The Board approved the proposed acquisition of 76 percent of the share capital of the
company by Deccan Consumer Holdings Limited, and authorised the Chairman to negotiate the
share purchase agreement. The Board noted that the transaction requires CCI approval.

## Appointment of advisers

Mehta & Rao Associates were appointed as legal counsel and Iyer Sundaram & Co as financial
due diligence advisers.
"""


def _pdf() -> bytes:
    import fitz
    doc = fitz.open()
    for lines in (IM_PAGE_1, IM_PAGE_2):
        page = doc.new_page()
        y = 72
        for i, line in enumerate(lines):
            heading = i == 0 or len(line) < 40
            size = 16 if i == 0 else (13 if heading else 10)
            box = fitz.Rect(56, y, 540, y + 200)
            page.insert_textbox(box, line, fontsize=size, fontname="helv")
            y += (24 if heading else 15 * (1 + len(line) // 95)) + 6
    # The scanned annexure: rasterise text into an image and place only the image.
    scratch = fitz.open()
    src = scratch.new_page()
    y = 80
    for line in IM_PAGE_3_SCAN:
        src.insert_text((60, y), line, fontsize=15, fontname="helv")
        y += 28
    png = src.get_pixmap(dpi=150).tobytes("png")
    page = doc.new_page()
    page.insert_image(page.rect, stream=png)
    doc.set_metadata({"title": "Project Nilgiri - Information Memorandum",
                      "author": "Fictional Advisors", "creationDate": "D:20250601000000",
                      "modDate": "D:20250601000000", "producer": "aura-fixtures"})
    return doc.tobytes(garbage=3, deflate=True, no_new_id=True)


def _docx() -> bytes:
    import docx
    document = docx.Document()
    for title, body in SPA_SECTIONS:
        if body is None:
            document.add_heading(title, level=0)
            continue
        document.add_heading(title, level=1)
        document.add_paragraph(body)
        if title.startswith("2."):
            table = document.add_table(rows=0, cols=3)
            for row in SPA_TRANCHES:
                cells = table.add_row().cells
                for c, v in zip(cells, row):
                    c.text = v
    document.core_properties.author = "Fictional Counsel"
    from datetime import datetime
    document.core_properties.created = datetime(2025, 6, 1)
    document.core_properties.modified = datetime(2025, 6, 1)
    out = io.BytesIO()
    document.save(out)
    return out.getvalue()


def _xlsx() -> bytes:
    import openpyxl
    wb = openpyxl.Workbook()
    wb.active.title = "P&L"
    for name, rows in (("P&L", PNL), ("Debt schedule", DEBT), ("Cap table", CAP_TABLE)):
        ws = wb[name] if name in wb.sheetnames else wb.create_sheet(name)
        for r in rows:
            ws.append(r)
    wb.create_sheet("Notes")  # empty: the parser warns about it
    from datetime import datetime
    wb.properties.created = datetime(2025, 6, 1)
    wb.properties.modified = datetime(2025, 6, 1)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def _pptx() -> bytes:
    from pptx import Presentation
    from pptx.util import Inches
    deck = Presentation()
    for title, bullets, table, notes in SLIDES:
        slide = deck.slides.add_slide(deck.slide_layouts[5])  # title only
        slide.shapes.title.text = title
        box = slide.shapes.add_textbox(Inches(0.5), Inches(1.5), Inches(9), Inches(2))
        box.text_frame.text = bullets[0]
        for b in bullets[1:]:
            box.text_frame.add_paragraph().text = b
        if table:
            shape = slide.shapes.add_table(len(table), len(table[0]), Inches(0.5),
                                           Inches(3.8), Inches(6), Inches(2))
            for i, row in enumerate(table):
                for j, v in enumerate(row):
                    shape.table.cell(i, j).text = v
        if notes:
            slide.notes_slide.notes_text_frame.text = notes
    from datetime import datetime
    deck.core_properties.created = datetime(2025, 6, 1)
    deck.core_properties.modified = datetime(2025, 6, 1)
    deck.core_properties.last_modified_by = "aura-fixtures"
    out = io.BytesIO()
    deck.save(out)
    return out.getvalue()


def _eml() -> bytes:
    msg = EmailMessage()
    msg["From"] = "Meera Iyer <meera@iyersundaram.example>"
    msg["To"] = "deal-team@aura.example"
    msg["Date"] = "Tue, 10 Jun 2025 18:05:00 +0530"
    msg["Subject"] = "FDD red flags - Kaveri Agro Foods"
    msg["Message-ID"] = "<fdd-nilgiri-001@iyersundaram.example>"
    msg.set_content(EMAIL_BODY)
    msg.add_attachment(TRACKER_CSV.encode(), maintype="text", subtype="csv",
                       filename="dd_tracker.csv")
    return msg.as_bytes()


FIXTURES = {
    "nilgiri_information_memorandum.pdf": _pdf,
    "nilgiri_spa_draft.docx": _docx,
    "nilgiri_financial_model.xlsx": _xlsx,
    "nilgiri_management_presentation.pptx": _pptx,
    "nilgiri_fdd_red_flags.eml": _eml,
    "nilgiri_board_minutes.md": lambda: BOARD_MINUTES.encode(),
    "nilgiri_dd_tracker.csv": lambda: TRACKER_CSV.encode(),
}


def build(target: Path = HERE) -> dict[str, Path]:
    target.mkdir(parents=True, exist_ok=True)
    out = {}
    for name, make in FIXTURES.items():
        path = target / name
        path.write_bytes(make())
        out[name] = path
    return out


if __name__ == "__main__":
    for name, path in build(Path(sys.argv[1]) if len(sys.argv) > 1 else HERE).items():
        print(f"{path.stat().st_size:>8}  {name}")
