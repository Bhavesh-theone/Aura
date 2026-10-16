"""Deal intake extraction: from an intake's indexed chunks to reviewed-ready fields.

Deterministic extractors run first, where they are reliable:
- statutory identifiers (CIN, PAN, GSTIN, LLPIN) by their formats, cited to the page;
- financial line items ('Revenue from operations', 'EBITDA', 'Profit for the year', 'Net
  debt') from table grids (Docling, XLSX, PPTX and DOCX tables keep their cells), in the latest
  actual fiscal-year column, with the reporting unit (crore, lakh, million) normalised to
  whole rupees; and the same items written in sentences ('revenue of ₹412.38 crore');
- names, the deal's code name, tenor, coupon, governing law, ticket size, regulatory hints.
The local model then fills the rest, one narrow field group at a time (identity, transaction,
parties, financials, terms, regulatory, class profile, mandate criteria): hybrid search over
the intake's chunks with group-specific queries (table chunks first for financials), the
passages screened for prompt injection and wrapped as untrusted data within a character
budget, temperature 0, JSON only. Every value - whoever proposed it - goes through the same
validators (aura.core.services.intake_fields).

Each field gets {value, confidence, citations, source}. Candidates that agree are merged
(their citations pooled, the confidence nudged up per extra document); candidates that
disagree become a conflict a person must resolve. Confidence is the extractor's (a model's
self-report times a validation multiplier: is the quote really in the cited chunk, is the
value really in the quote); below the threshold a field needs review, and valuation inputs
need 0.95 or a person's confirmation.

Pure: the caller hands in the chunks, a retrieve function and the model adapter.
"""
import re
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Callable

from aura.core.domain.enums import IdentifierScheme
from aura.core.policy.identifier_policy import normalise_identifier
from aura.core.policy.injection_policy import DEFAULT_THRESHOLD, screen, wrap
from aura.core.ports.intake import FieldExtractor
from aura.core.services import intake_fields as F
from aura.core.domain.intake import Candidate, Citation
from aura.core.domain.intake import StagedChunk as SourceChunk
from aura.core.services.intake_fields import FieldSpec

DETERMINISTIC = ("table", "regex")
LLM_GROUPS = ("identity", "transaction", "parties", "financials", "terms", "regulatory",
              "profile", "mandate")
GROUP_QUERIES = {
    "identity": "company legal name CIN PAN GSTIN registered office incorporated sector "
                "business overview",
    "transaction": "proposed transaction ticket size issue size instrument use of proceeds "
                   "purpose raise",
    "parties": "investors lenders shareholders buyer seller acquirer advisers counsel "
               "arranger trustee",
    "financials": "revenue from operations EBITDA profit for the year net debt statement of "
                  "profit and loss key financials",
    "terms": "tenor coupon interest rate security charge covenants governing law valuation "
             "stake",
    "regulatory": "regulatory approval RBI FEMA CCI SEBI listed foreign investment Press Note "
                  "3",
    "mandate": "investor criteria minimum rating ticket sector target investors mandate",
}
GROUP_FIELDS = {
    "identity": ("company_name", "cin", "pan", "gstin", "llpin", "registered_office",
                 "incorporation_date", "sector", "nic_code"),
    "transaction": ("deal_name", "transaction_class", "subclass", "ticket_size_inr", "purpose",
                    "side"),
    "parties": ("parties",),
    "financials": ("fiscal_year", "revenue_inr", "ebitda_inr", "pat_inr", "net_debt_inr"),
    "terms": ("tenor_months", "coupon_pct", "security", "covenants", "governing_law",
              "valuation_inr", "stake_pct"),
    "regulatory": ("regulatory_flags",),
    "mandate": ("mandate_criteria",),
}
LIST_FIELDS = ("parties", "regulatory_flags", "mandate_criteria")
QUOTE_CHARS = 200


@dataclass
class ExtractionSettings:
    threshold: float = F.DEFAULT_THRESHOLD
    top_k: int = 6
    context_chars: int = 5000
    injection_threshold: float = DEFAULT_THRESHOLD


@dataclass
class ExtractionResult:
    fields: dict[str, dict]
    conflicts: list[dict]
    transaction_class: str | None
    warnings: list[str]
    llm_used: bool
    llm_groups: list[str]
    duration_ms: int


Progress = Callable[[str, int, int, str], None]   # stage, done, total, message


# ============================================================ helpers

def _window(text: str, start: int, end: int, size: int = QUOTE_CHARS) -> str:
    pad = max(0, (size - (end - start)) // 2)
    a, b = max(0, start - pad), min(len(text), end + pad)
    while a > 0 and not text[a - 1].isspace() and a > start - pad - 20:
        a -= 1
    return text[a:b].strip()


def _flat(text: str) -> str:
    return " ".join(text.split())


# ============================================================ identifiers and names

_ID_PATTERNS = {
    "cin": (IdentifierScheme.CIN, re.compile(r"\b[LU]\d{5}[A-Z]{2}\d{4}[A-Z]{3}\d{6}\b")),
    "gstin": (IdentifierScheme.GSTIN, re.compile(r"\b\d{2}[A-Z]{5}\d{4}[A-Z][0-9A-Z]{3}\b")),
    "pan": (IdentifierScheme.PAN, re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")),
    "llpin": (IdentifierScheme.LLPIN, re.compile(r"\bLLPIN[\s:.-]*([A-Z]{3}-\d{4})\b")),
}
_COMPANY = re.compile(
    r"\b((?:[A-Z][A-Za-z0-9&'.-]*|&|and|of)(?:[ \t]+(?:[A-Z][A-Za-z0-9&'.-]*|&|and|of)){0,8}"
    r"[ \t]+(?:Private[ \t]+Limited|Pvt\.?[ \t]+Ltd\.?|Limited|Ltd\.?|LLP))(?![A-Za-z])")
_LEAD_NOISE = re.compile(r"^(?:(?:The|M/s\.?|Messrs\.?|Of|And|By|For|To|In|With|Issuer|"
                         r"Borrower|Company|Target|Shares|Board|Directors|Strictly|Private|"
                         r"Certified|True|Copy|Prepared|Proposed|NCD|NCDs)\s+)+")


def identifier_candidates(chunks: list[SourceChunk]) -> list[Candidate]:
    """One candidate per (field, value, document), cited to the first chunk it appears in.
    A PAN is not read out of a GSTIN (word boundaries), and a PAN labelled as someone
    else's (a director's, an investor's) is still a candidate: disagreement is a conflict."""
    seen: dict[tuple[str, str, int], Candidate] = {}
    for c in chunks:
        for key, (scheme, pattern) in _ID_PATTERNS.items():
            for m in pattern.finditer(c.text):
                raw = m.group(1) if m.groups() else m.group(0)
                try:
                    value = normalise_identifier(scheme, raw)
                except Exception:
                    continue
                k = (key, value, c.document_id)
                if k in seen:
                    continue
                labelled = re.search(rf"{scheme.value}\W{{0,4}}$", c.text[max(0, m.start() - 12):
                                                                         m.start()])
                seen[k] = Candidate(key, value, 0.93 if labelled else 0.88, "regex",
                                    [c.cite(_window(c.text, m.start(), m.end()))])
    return list(seen.values())


def company_name_candidates(chunks: list[SourceChunk]) -> list[Candidate]:
    """Registered names ('... Private Limited', '... LLP'), weighted by how often each
    appears and whether a CIN follows it closely; the best per document is a candidate."""
    per_doc: dict[int, Counter] = defaultdict(Counter)
    where: dict[tuple[int, str], tuple[SourceChunk, int, int]] = {}
    for c in chunks:
        for m in _COMPANY.finditer(c.text):
            name = _LEAD_NOISE.sub("", _flat(m.group(1))).strip(" ,.")
            if len(name.split()) < 2 or name.split()[0].lower() in ("limited", "private"):
                continue
            canon = F.canonical_text(name)
            near_cin = bool(re.search(r"\bCIN\b|\b[LU]\d{5}[A-Z]{2}", c.text[m.end():m.end() + 160]))
            per_doc[c.document_id][canon] += 3 if near_cin else 1
            where.setdefault((c.document_id, canon), (c, m.start(), m.end()))
    out: list[Candidate] = []
    for doc_id, counts in per_doc.items():
        canon, weight = counts.most_common(1)[0]
        c, a, b = where[(doc_id, canon)]
        name = _LEAD_NOISE.sub("", _flat(c.text[a:b])).strip(" ,.")
        name = re.sub(r"\bPvt\.?\s+Ltd\.?$", "Private Limited", name)
        conf = min(0.92, 0.72 + 0.05 * weight)
        out.append(Candidate("company_name", name, conf, "regex",
                             [c.cite(_window(c.text, a, b))]))
    return out


def _first(pattern: re.Pattern, chunks: list[SourceChunk], key: str, conf: float,
           convert: Callable[[re.Match], object] = lambda m: m.group(1),
           per_document: bool = True) -> list[Candidate]:
    out, docs = [], set()
    for c in chunks:
        if per_document and c.document_id in docs:
            continue
        m = pattern.search(c.text)
        if not m:
            continue
        value = convert(m)
        if value in (None, ""):
            continue
        docs.add(c.document_id)
        out.append(Candidate(key, value, conf, "regex", [c.cite(_window(c.text, m.start(),
                                                                          m.end()))]))
    return out


_OFFICE = re.compile(r"Registered\s+office\s*[:\-–]\s*([^\n|]{8,160}?)(?=\s*(?:\||\n|$|CIN|PAN))",
                     re.IGNORECASE)
_PROJECT = re.compile(r"\bProject\s+([A-Z][a-z]{2,20})\b")
_INCORPORATED = re.compile(r"incorporated\s+(?:on\s+)?(\d{1,2}(?:st|nd|rd|th)?\s+[A-Z][a-z]+"
                           r",?\s+\d{4}|\d{1,2}[/.-]\d{1,2}[/.-]\d{4}|\d{4}-\d{2}-\d{2})")
_TENOR = re.compile(r"\btenor\b[\s:.\-–]*(?:of\s+)?(\d{1,3})\s*(months?|years?)", re.IGNORECASE)
_COUPON = re.compile(r"\b(?:coupon|interest\s+rate)\b[\s:.\-–]*(?:of\s+)?(\d{1,2}(?:\.\d{1,3})?)"
                     r"\s*%", re.IGNORECASE)
_LAW = re.compile(r"governed\s+by\s+(?:and\s+construed\s+in\s+accordance\s+with\s+)?the\s+"
                  r"(laws?\s+of\s+(?:the\s+)?(?:Republic\s+of\s+)?[A-Z][a-z]+)|"
                  r"governing\s+law\s*[:\-–]\s*(laws?\s+of\s+[A-Z][a-z]+)", re.IGNORECASE)
_AMOUNT = r"(?:₹|INR|Rs\.?)\s*([0-9][0-9,]*(?:\.\d+)?)\s*(crores?|cr\.?|lakhs?|lacs?|million|mn|billion|bn)?\b"
_TICKET = re.compile(r"(?:ticket\s+size|issue\s+size|raise|raising|borrow\s+up\s+to|"
                     r"facility\s+(?:amount|size)|aggregating(?:\s+up\s+to)?|investment\s+of)"
                     r"[^.₹]{0,40}?" + _AMOUNT, re.IGNORECASE)
_SECURITY = re.compile(r"\bSecurity\b\s*[:\-–]?\s*((?:First|Second|Exclusive|Pari[ -]passu|"
                       r"Hypothecation|Mortgage|Pledge)(?:[^.\n]|\.(?=\d)){10,200})", re.IGNORECASE)
_STAKE = re.compile(r"(?:acquisition|sale|purchase|acquire|sell|stake)\s+of\s+(\d{1,3}(?:\.\d+)?)"
                    r"\s*(?:%|percent|per\s*cent)", re.IGNORECASE)


def _inr_from_match(m: re.Match, number_group: int = 1, unit_group: int = 2) -> int | None:
    unit = m.group(unit_group) or ""
    if not unit:
        return None   # a bare rupee figure in a sentence is too ambiguous
    return F.parse_inr(f"{m.group(number_group)} {unit}")


def _sentence_case(text: str) -> str:
    return text[:1].upper() + text[1:]


def _sentence(text: str, start: int, end: int, limit: int = 300) -> str:
    """The sentence (or line) holding text[start:end]."""
    a = max(text.rfind(". ", 0, start), text.rfind("\n", 0, start))
    b_candidates = [i for i in (text.find(". ", end), text.find("\n", end)) if i != -1]
    b = min(b_candidates) + 1 if b_candidates else len(text)
    return _flat(text[a + 1:b])[:limit]


def sentence_candidates(chunks: list[SourceChunk]) -> list[Candidate]:
    text_chunks = [c for c in chunks if c.kind == "text"] or chunks
    out: list[Candidate] = []
    out += _first(_OFFICE, chunks, "registered_office", 0.86,
                  lambda m: m.group(1).strip(" .,;"))
    out += _first(_INCORPORATED, text_chunks, "incorporation_date", 0.86,
                  lambda m: F.parse_date(m.group(1)))
    projects = Counter(m.group(1) for c in chunks for m in _PROJECT.finditer(c.text))
    if projects:
        name = projects.most_common(1)[0][0]
        out += _first(re.compile(rf"\bProject\s+({name})\b"), chunks, "deal_name",
                      0.9 if projects[name] >= 2 else 0.8, lambda m: f"Project {m.group(1)}")
    out += _first(_TENOR, chunks, "tenor_months", 0.9,
                  lambda m: F.parse_months(f"{m.group(1)} {m.group(2)}"))
    out += _first(_COUPON, chunks, "coupon_pct", 0.9, lambda m: float(m.group(1)))
    out += _first(_LAW, chunks, "governing_law", 0.88,
                  lambda m: _sentence_case(_flat(m.group(1) or m.group(2))))
    out += _first(_TICKET, chunks, "ticket_size_inr", 0.86, _inr_from_match)
    out += _first(_STAKE, chunks, "stake_pct", 0.8, lambda m: float(m.group(1)))
    out += _first(_SECURITY, chunks, "security", 0.82, lambda m: _flat(m.group(1)).strip(" ,;"))
    return out


# ============================================================ transaction class

# (pattern, weight): instrument and agreement names say more than words like 'lender'.
_CLASS_SIGNALS = {
    "DEBT": [(r"non-convertible debentures?|\bNCDs?\b", 3), (r"debenture trust deed", 3),
             (r"term loan|credit facility|working capital facility", 1),
             (r"\bborrow(?:ing)?s?\b|\blenders?\b|\bdebt\b|\bbonds?\b", 0.3)],
    "EQUITY": [(r"\bseries [a-e]\b", 3), (r"pre-money|post-money", 3),
               (r"equity (?:round|raise|investment|infusion)|primary (?:issue|infusion)", 2),
               (r"fund ?raise", 1)],
    "MNA": [(r"share purchase agreement|\bSPA\b", 3), (r"purchase price|sale shares", 2),
            (r"acquisition of|acquire[sd]?\b|acquirer|merger|scheme of arrangement", 2),
            (r"(?:sell|sale of) an? \d{1,3} ?(?:percent|%) stake|buyout|divestment", 3)],
    "HYBRID": [(r"compulsorily convertible|optionally convertible|\bCCDs?\b|\bOCDs?\b", 3),
               (r"mezzanine|structured equity", 2)],
    "JV": [(r"joint venture", 3), (r"\bJV\b", 2)],
    "LPGP": [(r"limited partners?|\bAIF\b|fund (?:commitment|corpus)|carried interest", 3),
             (r"management fee", 1)],
    "ALLIANCE": [(r"strategic alliance|distribution agreement|licensing agreement|"
                  r"co-marketing", 3)],
}
_SUBCLASS = [(r"non-convertible debenture|\bNCDs?\b", "NCD"), (r"term loan", "Term loan"),
             (r"working capital", "Working capital"),
             (r"\bseries ([A-E])\b", None), (r"compulsorily convertible preference", "CCPS"),
             (r"share purchase agreement|acquisition of", "Acquisition")]


def class_candidates(chunks: list[SourceChunk]) -> list[Candidate]:
    scores: Counter = Counter()
    first: dict[str, tuple[SourceChunk, re.Match, float]] = {}
    for c in chunks:
        for cls, patterns in _CLASS_SIGNALS.items():
            for pattern, weight in patterns:
                hits = list(re.finditer(pattern, c.text, re.IGNORECASE))
                if hits:
                    scores[cls] += weight * len(hits)
                    if cls not in first or first[cls][2] < weight:
                        first[cls] = (c, hits[0], weight)
    out: list[Candidate] = []
    if scores:
        (best, n), *rest = scores.most_common()
        runner = rest[0][1] if rest else 0
        share = n / max(1e-9, n + runner)
        c, m, _ = first[best]
        out.append(Candidate("transaction_class", best,
                             round(min(0.92, 0.45 + 0.5 * share), 3) if n >= 3 else 0.6,
                             "regex", [c.cite(_window(c.text, m.start(), m.end()))]))
    for pattern, label in _SUBCLASS:
        for c in chunks:
            m = re.search(pattern, c.text, re.IGNORECASE)
            if m:
                value = label or f"Series {m.group(1).upper()}"
                if c.text.lower().count("listed") and value == "NCD":
                    value = "Listed NCDs"
                out.append(Candidate("subclass", value, 0.75, "regex",
                                     [c.cite(_window(c.text, m.start(), m.end()))]))
                break
        if any(x.key == "subclass" for x in out):
            break
    return out


SIDE_FOR_CLASS = {"DEBT": "raise", "EQUITY": "raise", "HYBRID": "raise", "MNA": "sell",
                  "JV": "partner", "ALLIANCE": "partner", "LPGP": "raise"}


# ============================================================ financial tables

FINANCIAL_LABELS = {
    "revenue_inr": [r"revenue from operations", r"(?:total )?revenue(?: from operations)?",
                    r"net (?:sales|revenue)", r"(?:sales|turnover|net turnover)",
                    r"income from operations"],
    "ebitda_inr": [r"(?:adjusted |operating |reported )?ebitda"],
    "pat_inr": [r"profit (?:for|after tax for) the (?:year|period)", r"profit after tax",
                r"pat", r"net profit(?: after tax)?"],
    "net_debt_inr": [r"net debt", r"net borrowings"],
}
_UNIT_IN = re.compile(r"(?:₹|rs\.?|inr)\s*(?:in\s+)?(crores?|lakhs?|lacs?|millions?|mn)\b|"
                      r"\b(?:amounts?|figures?)\s+(?:are\s+)?in\s+(?:₹\s*|rs\.?\s*|inr\s*)?"
                      r"(crores?|lakhs?|lacs?|millions?)\b", re.IGNORECASE)
_EST = re.compile(r"\d\s*[EPFB]\b|\bproj|\best(?:imate)?|\bforecast|\bbudget|\bplan\b|"
                  r"\btarget\b", re.IGNORECASE)


def unit_word(text: str) -> str | None:
    m = _UNIT_IN.search(text or "")
    if not m:
        return None
    w = (m.group(1) or m.group(2) or "").lower()
    if w.startswith("cr"):
        return "crore"
    if w.startswith("la"):
        return "lakh"
    return "million"


def _year(text: str) -> int | None:
    t = text or ""
    m = re.search(r"\bFY\s*'?(\d{4}|\d{2})(?!\d)", t, re.IGNORECASE)
    if m:
        y = int(m.group(1))
        return y if y > 1900 else 2000 + y
    m = re.search(r"\b(20\d{2})\s*[-–/]\s*(\d{2})\b", t)
    if m:
        return 2000 + int(m.group(2))
    m = re.search(r"\b(20\d{2})\b", t)
    return int(m.group(1)) if m else None


def table_grid(chunk: SourceChunk) -> tuple[list[list[str]], list[list[str]], str] | None:
    """(header rows, body rows, caption) of a table chunk, cells as written."""
    if chunk.kind != "table":
        return None
    lines = chunk.text.split("\n")
    header_lines = [h for h in (chunk.meta.get("header") or "").split("\n") if h.strip()]
    start = 0
    if header_lines and header_lines[0] in lines:
        start = lines.index(header_lines[0])
    elif chunk.meta.get("heading") and lines and lines[0].strip() == chunk.meta["heading"]:
        start = 1
    n_header = max(1, len(header_lines))
    rows = [[cell.strip() for cell in line.split(" | ")] for line in lines[start:]]
    rows = [r for r in rows if any(r)]
    if len(rows) < 2:
        return None
    return rows[:n_header], rows[n_header:], "\n".join(lines[:start])


def _label(cell: str) -> str:
    low = re.sub(r"\(.*?\)", " ", cell.lower())
    low = re.sub(r"[^a-z& ]+", " ", low)
    return " ".join(low.split())


def _value_column(header: list[list[str]], columns: list[str] | None, width: int
                  ) -> tuple[int | None, int | None, bool]:
    """(column, year, explicit) of the latest actual fiscal year in the header."""
    best: tuple[int, int] | None = None
    for col in range(1, width):
        text = " ".join(r[col] for r in header if col < len(r))
        if columns and col < len(columns):
            text += " " + columns[col]
        if re.search(r"\bnotes?\b", text, re.IGNORECASE):
            continue
        year = _year(text)
        if year is None or _EST.search(text):
            continue
        if best is None or year > best[1]:
            best = (col, year)
    return (best[0], best[1], True) if best else (None, None, False)


def table_candidates(chunks: list[SourceChunk]) -> list[Candidate]:
    by_doc: dict[int, list[SourceChunk]] = defaultdict(list)
    for c in chunks:
        by_doc[c.document_id].append(c)
    doc_unit = {d: Counter(u for u in (unit_word(c.text) for c in cs) if u).most_common(1)
                for d, cs in by_doc.items()}
    out: list[Candidate] = []
    found: set[tuple[str, int]] = set()
    for c in chunks:
        grid = table_grid(c)
        if grid is None:
            continue
        header, body, caption = grid
        width = max(len(r) for r in header + body)
        col, year, explicit = _value_column(header, c.meta.get("columns"), width)
        local_unit = unit_word(" ".join([caption, c.meta.get("heading") or "",
                                         " ".join(" ".join(r) for r in header)]))
        unit = local_unit or (doc_unit[c.document_id][0][0] if doc_unit[c.document_id] else None)
        if unit is None:
            continue
        for row in body:
            label = _label(row[0]) if row else ""
            if not label:
                continue
            for key, patterns in FINANCIAL_LABELS.items():
                if (key, c.document_id) in found:
                    continue
                if not any(re.fullmatch(p, label) for p in patterns):
                    continue
                cell, explicit_col = None, explicit
                if col is not None and col < len(row) and F.parse_number(row[col]) is not None:
                    cell = row[col]
                else:
                    numeric = [x for x in row[1:] if F.parse_number(x) is not None
                               and not re.fullmatch(r"\d{1,2}", x.strip())]
                    if numeric:
                        cell, explicit_col = numeric[0], False
                if cell is None:
                    continue
                value = F.parse_inr(F.parse_number(cell), unit)
                conf = 0.93 if explicit_col and local_unit else (
                    0.9 if explicit_col else 0.82)
                quote = " | ".join(x for x in row if x)
                note = (f"FY{year % 100:02d} · " if year and explicit_col else "") + \
                    f"reported in ₹ {unit}"
                out.append(Candidate(key, value, conf, "table", [c.cite(quote)], note=note))
                found.add((key, c.document_id))
                if year and explicit_col:
                    out.append(Candidate("fiscal_year", f"FY{year % 100:02d}", conf, "table",
                                         [c.cite(" | ".join(x for x in header[-1] if x))]))
                out.append(Candidate("reporting_unit", unit, conf, "table", [c.cite(quote)]))
    return out


_SENTENCE_FIN = {
    "revenue_inr": r"revenue(?:\s+from\s+operations)?",
    "ebitda_inr": r"\bEBITDA",
    "pat_inr": r"(?:profit after tax|\bPAT\b|net profit)",
    "net_debt_inr": r"net debt",
}


def sentence_financial_candidates(chunks: list[SourceChunk]) -> list[Candidate]:
    out: list[Candidate] = []
    for key, label in _SENTENCE_FIN.items():
        pattern = re.compile(label + r"[^.₹\n]{0,60}?(?:was|of|is|at|stood at|:)\s*" + _AMOUNT,
                             re.IGNORECASE)
        docs: set[int] = set()
        for c in chunks:
            if c.document_id in docs or c.kind == "table":
                continue
            m = pattern.search(c.text)
            if not m:
                continue
            value = _inr_from_match(m)
            if value is None:
                continue
            docs.add(c.document_id)
            out.append(Candidate(key, value, 0.88, "regex",
                                 [c.cite(_window(c.text, m.start(), m.end()))]))
    return out


# ============================================================ regulatory hints

_REG = {
    "SEBI": r"listed on (?:the )?(?:wholesale debt market|BSE|NSE)|\bSEBI\b|listed (?:NCDs|"
            r"debentures)|open offer|takeover code",
    "CCI": r"\bCCI\b|Competition Commission|combination (?:notice|approval)",
    "FEMA": r"\bFEMA\b|foreign (?:direct )?investment|\bFDI\b|non-resident|\bECB\b|"
            r"external commercial borrowing",
    "RBI": r"\bRBI\b|Reserve Bank of India|\bNBFC\b|\bECB\b",
    "PRESS_NOTE_3": r"Press Note 3|land border",
}


def regulatory_candidates(chunks: list[SourceChunk]) -> list[Candidate]:
    flags: list[dict] = []
    cites: list[Citation] = []
    for flag, pattern in _REG.items():
        for c in chunks:
            m = re.search(pattern, c.text, re.IGNORECASE)
            if m:
                quote = _sentence(c.text, m.start(), m.end())
                flags.append({"flag": flag, "reason": quote, "include": True})
                cites.append(c.cite(quote))
                break
    if not flags:
        return []
    return [Candidate("regulatory_flags", flags, 0.75, "regex", cites)]


# ============================================================ deterministic suite

def deterministic_candidates(chunks: list[SourceChunk]) -> list[Candidate]:
    return [*identifier_candidates(chunks), *company_name_candidates(chunks),
            *sentence_candidates(chunks), *class_candidates(chunks),
            *table_candidates(chunks), *sentence_financial_candidates(chunks),
            *regulatory_candidates(chunks)]


# ============================================================ the model's turn

def _passages(chunk_ids: list[int], by_id: dict[int, SourceChunk], budget: int,
              threshold: float, warnings: list[str]) -> tuple[str, dict[str, SourceChunk]]:
    tags: dict[str, SourceChunk] = {}
    parts: list[str] = []
    used = 0
    for cid in chunk_ids:
        c = by_id.get(cid)
        if c is None:
            continue
        result = screen(c.text)
        if result.flagged(threshold):
            warnings.append(f"{c.filename}: a passage was left out of the model's context "
                            f"(prompt-injection screening: {', '.join(result.matched_rules)})")
            continue
        tag = f"C{len(tags) + 1}"
        page = f" p.{c.page_from}" if c.page_from else ""
        head = f"[{tag}] {c.filename}{page}{' (table)' if c.kind == 'table' else ''}\n"
        body = result.text
        room = budget - used - len(head)
        if room < 200:
            break
        body = body[:room]
        parts.append(head + body)
        used += len(head) + len(body)
        tags[tag] = c
    return wrap("\n\n".join(parts), "intake documents"), tags


def _field_brief(spec: FieldSpec) -> dict:
    hint = {"inr": "amount exactly as written, with its unit (e.g. '₹412.38 crore')",
            "percent": "number (percent)", "integer": "whole number",
            "date": "date as written", "identifier": "exact code",
            "string_list": "list of short strings",
            "enum": "one of: " + ", ".join(spec.options or ()),
            "boolean": "true or false", "json": "JSON value"}.get(spec.type, "text")
    return {"key": spec.key, "label": spec.label, "description": spec.description or "",
            "type": spec.type, "format": hint, "options": list(spec.options or [])}


def _cite_llm(raw: dict, tags: dict[str, SourceChunk], value_text: str
              ) -> tuple[list[Citation], float]:
    """Citations for a model answer and the validation multiplier: 1.0 when its quote is in
    the cited passage and holds the value, 0.85 when only one of the two holds, 0.6 when the
    value cannot be found in any passage it was shown."""
    tag = str(raw.get("chunk") or raw.get("source") or "").strip().strip("[]")
    chunk = tags.get(tag)
    quote = _flat(str(raw.get("quote") or ""))
    candidates = [chunk] if chunk else []
    candidates += [c for c in tags.values() if c is not chunk]
    probe = value_text.strip()
    for c in candidates:
        flat = _flat(c.text)
        quote_ok = bool(quote) and quote.lower() in flat.lower()
        value_ok = bool(probe) and probe.lower() in flat.lower()
        if quote_ok or value_ok:
            if quote_ok:
                q = quote
            else:
                i = flat.lower().index(probe.lower())
                q = _window(flat, i, i + len(probe))
            multiplier = 1.0 if (quote_ok and (value_ok or not probe) and c is chunk) else 0.85
            return [c.cite(q)], multiplier
    if chunk is not None:
        return [chunk.cite(quote or chunk.text[:QUOTE_CHARS])], 0.6
    return [], 0.6


def _value_probe(raw_value: object) -> str:
    """The part of a model's answer that should literally appear in the passage."""
    if isinstance(raw_value, (int, float)) and not isinstance(raw_value, bool):
        return f"{raw_value:g}"
    text = str(raw_value or "")
    num = re.search(r"[0-9][0-9,]*(?:\.[0-9]+)?", text)
    if num and re.search(r"(crore|lakh|million|₹|inr|rs|%|month|year)", text, re.IGNORECASE):
        return num.group(0)
    return text[:60]


def llm_candidates(group: str, specs: list[FieldSpec], answer: dict | None,
                   tags: dict[str, SourceChunk], unit: str | None,
                   errors: dict[str, str]) -> list[Candidate]:
    out: list[Candidate] = []
    if not isinstance(answer, dict):
        return out
    for spec in specs:
        raw = answer.get(spec.key)
        if raw is None and spec.key.startswith(F.PROFILE_PREFIX):
            raw = answer.get(spec.key[len(F.PROFILE_PREFIX):])
        if raw is None:
            continue
        if spec.type in ("parties", "flags", "criteria"):
            items = raw.get("value") if isinstance(raw, dict) else raw
            value, _ = F.normalise_value(spec, items)
            if not value:
                continue
            cites: list[Citation] = []
            for item in items if isinstance(items, list) else []:
                if isinstance(item, dict):
                    probe = str(item.get("name") or item.get("flag") or "")
                    got, _ = _cite_llm(item, tags, probe)
                    cites += got
            if spec.type in ("parties", "criteria"):
                # the model's suggestions start unticked: a person opts each one in
                value = [{**p, "include": False} for p in value]
            seen, uniq = set(), []
            for c in cites:
                if c.chunk_id not in seen:
                    seen.add(c.chunk_id)
                    uniq.append(c)
            out.append(Candidate(spec.key, value, 0.7, "llm", uniq[:6]))
            continue
        if isinstance(raw, dict):
            raw_value, self_conf = raw.get("value"), raw.get("confidence")
        else:
            raw_value, self_conf = raw, None
        if raw_value in (None, "", [], "null"):
            continue
        value, error = F.normalise_value(spec, raw_value, unit)
        if value is None:
            if error:
                errors.setdefault(spec.key, f"The model read {str(raw_value)[:60]!r}: {error}")
            continue
        conf = float(self_conf) if isinstance(self_conf, (int, float)) and not isinstance(
            self_conf, bool) and 0 <= self_conf <= 1 else 0.7
        cites, multiplier = _cite_llm(raw if isinstance(raw, dict) else {}, tags,
                                      _value_probe(raw_value))
        out.append(Candidate(spec.key, value, round(min(0.9, conf * multiplier), 3), "llm",
                             cites))
    return out


# ============================================================ merging

def _score(cands: list[Candidate]) -> float:
    docs = set().union(*(c.document_ids for c in cands)) if cands else set()
    best = max(c.confidence for c in cands)
    mixed = any(c.source in DETERMINISTIC for c in cands) and any(c.source == "llm"
                                                                   for c in cands)
    return min(0.99, best + 0.03 * max(0, len(docs) - 1) + (0.03 if mixed else 0.0))


def _rep(cands: list[Candidate]) -> Candidate:
    order = {"table": 0, "regex": 1, "llm": 2}
    return sorted(cands, key=lambda c: (order.get(c.source, 3), -c.confidence))[0]


def _pool(cands: list[Candidate], limit: int = 5) -> list[dict]:
    seen, out = set(), []
    for c in sorted(cands, key=lambda c: (c.source == "llm", -c.confidence)):
        for cite in c.citations:
            if cite.chunk_id not in seen:
                seen.add(cite.chunk_id)
                out.append(cite.as_dict())
    return out[:limit]


def merge_list(spec: FieldSpec, cands: list[Candidate]) -> dict | None:
    items: list[dict] = []
    ident = {"parties": lambda x: (F.canonical_text(x["name"]), x["role"]),
             "flags": lambda x: x["flag"],
             "criteria": lambda x: x["criterion_key"]}[spec.type]
    for c in sorted(cands, key=lambda c: c.source == "llm"):
        for item in c.value or []:
            if all(ident(item) != ident(i) for i in items):
                items.append(item)
    if not items:
        return None
    rep = _rep(cands)
    return {"value": items, "auto_value": items, "confidence": round(_score(cands), 3),
            "source": rep.source, "citations": _pool(cands, 8), "note": None, "error": None}


def merge_field(spec: FieldSpec, cands: list[Candidate], n: int
                ) -> tuple[dict | None, dict | None]:
    """(field record, conflict or None) from every candidate for one field."""
    cands = [c for c in cands if c.value is not None]
    if not cands:
        return None, None
    if spec.type in ("parties", "flags", "criteria"):
        return merge_list(spec, cands), None
    if any(c.source in DETERMINISTIC for c in cands):
        det = [c for c in cands if c.source in DETERMINISTIC]
        cands = [c for c in cands if c.source in DETERMINISTIC or c.confidence >= 0.5
                 or any(F.same_value(spec, c.value, d.value) for d in det)]
    clusters: list[list[Candidate]] = []
    for c in sorted(cands, key=lambda c: -c.confidence):
        for cl in clusters:
            if F.same_value(spec, cl[0].value, c.value):
                cl.append(c)
                break
        else:
            clusters.append([c])
    clusters.sort(key=lambda cl: (-_score(cl), _rep(cl).source == "llm"))
    best = clusters[0]
    rep = _rep(best)
    record = {"value": rep.value, "auto_value": rep.value, "confidence": round(_score(best), 3),
              "source": rep.source, "citations": _pool(best),
              "note": next((c.note for c in best if c.note), None), "error": None}
    conflict = None
    if len(clusters) > 1:
        conflict = {"id": f"c{n}", "field": spec.key, "label": spec.label,
                    "candidates": [{"value": _rep(cl).value,
                                    "display": F.display_value(spec, _rep(cl).value),
                                    "source": _rep(cl).source,
                                    "confidence": round(_score(cl), 3),
                                    "citations": _pool(cl, 3)} for cl in clusters[:4]],
                    "chosen": None, "resolved": False}
        record["conflict_id"] = conflict["id"]
    return record, conflict


# ============================================================ profile and mandate

COMMON_TO_PROFILE = {
    "ticket_size_inr": ("amount_inr", "commitment_inr", "initial_capital_inr"),
    "tenor_months": ("tenor_months", "term_months"),
    "coupon_pct": ("interest_rate_pct", "coupon_pct"),
    "security": ("security_package.primary",),
    "purpose": ("end_use",),
    "stake_pct": ("stake_pct",),
    "sector": ("target_sector", "sector"),
}


def derived_profile_candidates(records: dict[str, dict], profile_specs: list[FieldSpec]
                               ) -> list[Candidate]:
    keys = {s.key for s in profile_specs}
    out: list[Candidate] = []
    for common, targets in COMMON_TO_PROFILE.items():
        rec = records.get(common)
        if not rec or rec.get("value") is None:
            continue
        for t in targets:
            key = F.PROFILE_PREFIX + t
            if key in keys:
                spec = next(s for s in profile_specs if s.key == key)
                value, error = F.normalise_value(spec, rec["value"])
                if value is not None and not error:
                    out.append(Candidate(key, value, round(rec["confidence"] * 0.97, 3),
                                         rec["source"], [Citation(**c) for c in
                                                         rec.get("citations") or []]))
                break
    covenants = records.get("covenants")
    if covenants and covenants.get("value") and F.PROFILE_PREFIX + "covenants" in keys:
        out.append(Candidate(F.PROFILE_PREFIX + "covenants",
                             [{"name": str(c)[:120]} for c in covenants["value"]],
                             round(covenants["confidence"] * 0.95, 3), covenants["source"],
                             [Citation(**c) for c in covenants.get("citations") or []]))
    sub = (records.get("subclass") or {}).get("value") or ""
    if F.PROFILE_PREFIX + "facility_type" in keys and sub:
        low = sub.lower()
        facility = "ncd" if "ncd" in low or "debenture" in low else (
            "term_loan" if "term loan" in low else (
                "working_capital" if "working capital" in low else None))
        if facility:
            rec = records["subclass"]
            out.append(Candidate(F.PROFILE_PREFIX + "facility_type", facility,
                                 round(rec["confidence"], 3), rec["source"],
                                 [Citation(**c) for c in rec.get("citations") or []]))
    return out


def suggested_criteria(records: dict[str, dict]) -> list[Candidate]:
    crit: list[dict] = []
    cites: list[Citation] = []

    def value(key):
        return (records.get(key) or {}).get("value")

    def cite(key):
        cites.extend(Citation(**c) for c in (records.get(key) or {}).get("citations", [])[:1])

    if value("ticket_size_inr"):
        crit.append({"criterion_key": "ticket_size_inr", "operator": "lte",
                     "value": value("ticket_size_inr"), "hardness": "hard", "weight": None,
                     "include": True})
        cite("ticket_size_inr")
    if value("tenor_months"):
        crit.append({"criterion_key": "tenor_months", "operator": "gte",
                     "value": value("tenor_months"), "hardness": "soft", "weight": 0.6,
                     "include": True})
        cite("tenor_months")
    if value("subclass"):
        crit.append({"criterion_key": "instrument", "operator": "eq",
                     "value": value("subclass"), "hardness": "hard", "weight": None,
                     "include": True})
        cite("subclass")
    if value("sector"):
        crit.append({"criterion_key": "sector", "operator": "contains",
                     "value": value("sector"), "hardness": "preference", "weight": None,
                     "include": True})
        cite("sector")
    return [Candidate("mandate_criteria", crit, 0.8, "regex", cites)] if crit else []


# ============================================================ the run

def _needs_model(group: str, specs: list[FieldSpec], records: dict[str, dict],
                 threshold: float) -> bool:
    if group in ("parties", "regulatory", "mandate", "profile"):
        return True
    return any((records.get(s.key) or {}).get("confidence", 0) < threshold for s in specs)


def _known(group: str, records: dict[str, dict]) -> str:
    """Facts already read deterministically that frame the model's answer (written by
    code, outside the untrusted block)."""
    if group != "financials":
        return ""
    fy = (records.get("fiscal_year") or {}).get("value")
    unit = (records.get("reporting_unit") or {}).get("value")
    parts = []
    if fy:
        parts.append(f"The latest actual fiscal year in these documents is {fy}: give figures "
                     f"for {fy} only.")
    if unit:
        parts.append(f"The documents report amounts in ₹ {unit}.")
    return " ".join(parts)


def run_extraction(chunks: list[SourceChunk], retrieve: Callable[[str, int], list[int]],
                   extractor: FieldExtractor | None, schema_for: Callable[[str], dict | None],
                   hints: dict | None = None, settings: ExtractionSettings | None = None,
                   progress: Progress | None = None) -> ExtractionResult:
    """Extract every field from the intake's chunks. `retrieve(query, k)` returns chunk ids
    best first (hybrid search over the intake); `extractor` is the local model (None:
    deterministic only); `schema_for(class)` the class's deal-profile JSON Schema."""
    settings = settings or ExtractionSettings()
    started = time.perf_counter()
    report = progress or (lambda *a: None)
    warnings: list[str] = []
    by_id = {c.chunk_id: c for c in chunks}
    candidates: dict[str, list[Candidate]] = defaultdict(list)
    model_errors: dict[str, str] = {}
    report("extracting", 0, 1, "Reading identifiers and financial tables")
    for cand in deterministic_candidates(chunks):
        candidates[cand.key].append(cand)

    def merged() -> tuple[dict[str, dict], list[dict]]:
        records, conflicts = {}, []
        for spec in F.BASE_FIELDS:
            rec, conflict = merge_field(spec, candidates.get(spec.key, []), len(conflicts) + 1)
            if rec:
                records[spec.key] = rec
            if conflict:
                conflicts.append(conflict)
        return records, conflicts

    records, _ = merged()
    cls = (hints or {}).get("transaction_class_hint") or (records.get("transaction_class")
                                                          or {}).get("value")
    unit = (records.get("reporting_unit") or {}).get("value")
    groups = [g for g in LLM_GROUPS if g != "profile" or schema_for(cls) is not None] \
        if extractor is not None else []
    llm_groups: list[str] = []
    for i, group in enumerate(groups):
        if group == "profile":
            if not cls or schema_for(cls) is None:
                continue
            specs = [s for s in F.profile_fields(schema_for(cls))
                     if s.type != "json" and not any(
                         c.key == s.key for c in derived_profile_candidates(records, [s]))]
            query = " ".join(s.label for s in specs)[:400]
        else:
            specs = [F.BASE_BY_KEY[k] for k in GROUP_FIELDS[group]]
            query = GROUP_QUERIES[group]
        if not specs or not _needs_model(group, specs, records, settings.threshold):
            report("extracting", i + 1, len(groups) + 1, f"Skipped {group}: already found")
            continue
        if group not in ("parties", "regulatory", "mandate"):
            # The model fills the rest: fields already read confidently are not asked
            # again (a second reading of a table figure would only add noise).
            specs = [s for s in specs if (records.get(s.key) or {}).get(
                "confidence", 0) < settings.threshold]
        report("extracting", i + 1, len(groups) + 1, f"Asking the model about {group}")
        ids = retrieve(query, settings.top_k)
        if group == "financials":
            ids = sorted(ids, key=lambda cid: (by_id.get(cid) and by_id[cid].kind) != "table")
        passages, tags = _passages(ids, by_id, settings.context_chars,
                                   settings.injection_threshold, warnings)
        if not tags:
            continue
        known = _known(group, records)
        if known:
            passages = f"{known}\n\n{passages}"
        try:
            answer = extractor.extract(group, [_field_brief(s) for s in specs], passages, cls)
        except Exception as exc:
            if _transient(exc):
                raise
            warnings.append(f"The model could not answer for {group}: "
                            f"{type(exc).__name__}: {str(exc)[:160]}")
            continue
        llm_groups.append(group)
        if answer is None:
            warnings.append(f"The model's answer for {group} was not usable JSON")
            continue
        for cand in llm_candidates(group, specs, answer, tags, unit, model_errors):
            candidates[cand.key].append(cand)
        records, _ = merged()
        if group == "transaction" and not (hints or {}).get("transaction_class_hint"):
            cls = (records.get("transaction_class") or {}).get("value") or cls
    records, conflicts = merged()
    if not (hints or {}).get("transaction_class_hint"):
        cls = (records.get("transaction_class") or {}).get("value") or cls
    if cls and "side" not in records and cls in SIDE_FOR_CLASS:
        records["side"] = {"value": SIDE_FOR_CLASS[cls], "auto_value": SIDE_FOR_CLASS[cls],
                           "confidence": 0.6, "source": "regex", "citations": [],
                           "note": f"Usual side for a {cls} mandate", "error": None}
    # Criteria derived from the extracted terms come first; the model's suggestions follow
    # (unticked), minus any on a key already covered.
    derived = suggested_criteria(records)
    if derived:
        model = [c for c in candidates.get("mandate_criteria", []) if c.source == "llm"]
        keys = {c["criterion_key"] for c in derived[0].value}
        for c in model:
            c.value = [x for x in c.value if x["criterion_key"] not in keys
                       and not any(x["criterion_key"].startswith(k.split("_")[0])
                                   for k in keys)]
        rec = merge_list(F.BASE_BY_KEY["mandate_criteria"], derived + [c for c in model
                                                                      if c.value])
        if rec:
            records["mandate_criteria"] = rec
    if "deal_name" not in records and (records.get("company_name") or {}).get("value"):
        first = records["company_name"]["value"].split()[0]
        records["deal_name"] = {"value": f"Project {first}", "auto_value": f"Project {first}",
                                "confidence": 0.6, "source": "regex",
                                "citations": records["company_name"]["citations"][:1],
                                "note": "Suggested from the company name", "error": None}
    profile_specs = F.profile_fields(schema_for(cls)) if cls else []
    for cand in derived_profile_candidates(records, profile_specs):
        candidates[cand.key].append(cand)
    for spec in profile_specs:
        rec, conflict = merge_field(spec, candidates.get(spec.key, []), len(conflicts) + 1)
        if rec:
            records[spec.key] = rec
        if conflict:
            conflicts.append(conflict)
    for key, message in F.sanity_errors({k: r.get("value") for k, r in records.items()}).items():
        records[key]["note"] = message
        records[key]["confidence"] = min(records[key]["confidence"], 0.5)
    for key, message in model_errors.items():
        if key not in records:
            records[key] = {"value": None, "auto_value": None, "confidence": None,
                            "source": "llm", "citations": [], "note": None, "error": message}
    report("extracting", 1, 1, "Done")
    return ExtractionResult(fields=records, conflicts=conflicts, transaction_class=cls,
                            warnings=warnings, llm_used=bool(llm_groups),
                            llm_groups=llm_groups,
                            duration_ms=int((time.perf_counter() - started) * 1000))


def _transient(exc: Exception) -> bool:
    from aura.core.policy.retry_policy import is_transient
    return is_transient(exc)
