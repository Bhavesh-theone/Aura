"""Deal intake fields: what an intake extracts, and the deterministic normalisers and
validators every value passes through, whoever proposed it (a regex, a table grid, the local
model or the person reviewing).

Values are stored normalised: rupee amounts as whole rupees (an int; never crore or lakh),
dates as ISO 'YYYY-MM-DD', identifiers upper-case in their statutory format, percentages as
numbers (11.25 for 11.25%), enums as their value. Pure: no I/O.
"""
import re
from dataclasses import dataclass
from datetime import date, datetime

from aura.core.domain.enums import (CriterionHardness, CriterionOperator, IdentifierScheme,
                                    MandateSide, PartyRole, PartyType, TransactionClass)
from aura.core.domain.errors import RuleViolation
from aura.core.domain.intake import Candidate, Citation  # noqa: F401 (re-exported)
from aura.core.policy.identifier_policy import normalise_identifier

GROUPS: list[tuple[str, str]] = [
    ("identity", "Company"), ("transaction", "Transaction"), ("parties", "Parties"),
    ("financials", "Financials"), ("terms", "Terms"), ("regulatory", "Regulatory"),
    ("profile", "Deal profile"), ("mandate", "Mandate criteria")]
REGULATORY_FLAGS = ("RBI", "FEMA", "CCI", "SEBI", "PRESS_NOTE_3")
REPORTING_UNITS = ("crore", "lakh", "million", "rupees")
# Below this an extracted value is flagged for a person (settings.intake_confidence_threshold).
DEFAULT_THRESHOLD = 0.85
# Inputs to a valuation are confident (>= 0.95) or confirmed by a person, like extraction.
VALUATION_CONFIDENCE = 0.95


@dataclass(frozen=True)
class FieldSpec:
    key: str
    group: str
    label: str
    type: str          # text textarea inr number integer percent date enum identifier boolean
    #                    string_list parties criteria flags json
    description: str | None = None
    options: tuple[str, ...] | None = None
    enum_labels: dict | None = None
    required: bool = False
    valuation: bool = False         # feeds a valuation: 0.95-or-human
    scheme: IdentifierScheme | None = None
    minimum: float | None = None
    maximum: float | None = None
    max_length: int | None = None

    def as_dict(self) -> dict:
        return {"key": self.key, "group": self.group, "label": self.label, "type": self.type,
                "description": self.description,
                "options": list(self.options) if self.options else None,
                "enum_labels": dict(self.enum_labels) if self.enum_labels else None,
                "required": self.required}


_C = [c.value for c in TransactionClass]
BASE_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec("company_name", "identity", "Company name", "text", required=True,
              description="Registered legal name of the company the deal is about."),
    FieldSpec("cin", "identity", "CIN", "identifier", scheme=IdentifierScheme.CIN,
              description="Corporate Identification Number (21 characters)."),
    FieldSpec("llpin", "identity", "LLPIN", "identifier", scheme=IdentifierScheme.LLPIN,
              description="LLP Identification Number (AAA-0000)."),
    FieldSpec("pan", "identity", "PAN", "identifier", scheme=IdentifierScheme.PAN,
              description="Permanent Account Number of the company."),
    FieldSpec("gstin", "identity", "GSTIN", "identifier", scheme=IdentifierScheme.GSTIN,
              description="GST registration number."),
    FieldSpec("registered_office", "identity", "Registered office", "textarea",
              max_length=500, description="Registered office address."),
    FieldSpec("incorporation_date", "identity", "Incorporation date", "date",
              description="Date of incorporation (YYYY-MM-DD)."),
    FieldSpec("sector", "identity", "Sector", "text", max_length=120,
              description="Industry or sector the company operates in."),
    FieldSpec("nic_code", "identity", "NIC code", "text", max_length=8,
              description="National Industrial Classification code, if stated."),
    FieldSpec("deal_name", "transaction", "Deal name", "text", required=True, max_length=200,
              description="Working name of the deal, e.g. 'Project Kaveri'."),
    FieldSpec("transaction_class", "transaction", "Transaction class", "enum", required=True,
              options=tuple(_C), enum_labels={"DEBT": "Debt", "EQUITY": "Equity",
                                               "MNA": "M&A", "HYBRID": "Hybrid", "JV": "Joint venture",
                                               "LPGP": "LP / GP (funds)",
                                               "ALLIANCE": "Strategic alliance"},
              description="Kind of transaction."),
    FieldSpec("subclass", "transaction", "Instrument / subclass", "text", max_length=120,
              description="Instrument or sub-type, e.g. 'Listed NCDs', 'Series B', 'Term loan'."),
    FieldSpec("ticket_size_inr", "transaction", "Ticket size", "inr", minimum=0,
              description="Amount being raised, invested or paid."),
    FieldSpec("purpose", "transaction", "Purpose / use of proceeds", "textarea",
              max_length=500, description="What the money is for."),
    FieldSpec("side", "transaction", "Our side", "enum",
              options=tuple(s.value for s in MandateSide),
              description="Which side of the deal the firm advises."),
    FieldSpec("parties", "parties", "Parties", "parties",
              description="Other parties named in the documents (investors, lenders, buyers, "
                          "advisers)."),
    FieldSpec("fiscal_year", "financials", "Fiscal year", "text", max_length=16,
              description="Fiscal year the figures are for (latest full year), e.g. FY24."),
    FieldSpec("reporting_unit", "financials", "Reported in", "enum", options=REPORTING_UNITS,
              description="Unit the source documents report amounts in."),
    FieldSpec("revenue_inr", "financials", "Revenue from operations", "inr", valuation=True,
              minimum=0, description="Revenue from operations for the latest fiscal year."),
    FieldSpec("ebitda_inr", "financials", "EBITDA", "inr", valuation=True,
              description="EBITDA for the latest fiscal year."),
    FieldSpec("pat_inr", "financials", "Profit after tax", "inr", valuation=True,
              description="Profit for the year (PAT) for the latest fiscal year."),
    FieldSpec("net_debt_inr", "financials", "Net debt", "inr", valuation=True,
              description="Borrowings less cash and cash equivalents, at year end."),
    FieldSpec("tenor_months", "terms", "Tenor (months)", "integer", minimum=1, maximum=480,
              description="Tenor of the instrument in months."),
    FieldSpec("coupon_pct", "terms", "Coupon / rate (% p.a.)", "percent", minimum=0,
              maximum=50, description="Coupon or interest rate per annum."),
    FieldSpec("security", "terms", "Security", "textarea", max_length=500,
              description="Security or collateral offered."),
    FieldSpec("covenants", "terms", "Covenants", "string_list",
              description="Financial and other covenants."),
    FieldSpec("governing_law", "terms", "Governing law", "text", max_length=120,
              description="Governing law of the transaction documents."),
    FieldSpec("valuation_inr", "terms", "Valuation", "inr", valuation=True, minimum=0,
              description="Enterprise or equity valuation, if stated."),
    FieldSpec("stake_pct", "terms", "Stake (%)", "percent", minimum=0, maximum=100,
              description="Stake being sold, bought or issued."),
    FieldSpec("regulatory_flags", "regulatory", "Regulatory flags", "flags",
              options=REGULATORY_FLAGS,
              description="Regimes the deal touches: RBI, FEMA, CCI, SEBI, Press Note 3."),
    FieldSpec("mandate_criteria", "mandate", "Mandate criteria", "criteria",
              description="Suggested hard / soft / preference criteria for the mandate."),
)
BASE_BY_KEY = {f.key: f for f in BASE_FIELDS}
PROFILE_PREFIX = "profile."


# ------------------------------------------------------------------ class-specific profile

def _profile_spec(key: str, prop: dict) -> FieldSpec:
    t = prop.get("type")
    leaf = key.rsplit(".", 1)[-1]
    common = dict(description=prop.get("description"), label=prop.get("title") or leaf,
                  minimum=prop.get("minimum"), maximum=prop.get("maximum"),
                  max_length=prop.get("maxLength"))
    if "enum" in prop:
        return FieldSpec(key, "profile", type="enum", options=tuple(prop["enum"]),
                         enum_labels=prop.get("x-enum-labels"), **common)
    if t == "string":
        kind = "date" if prop.get("format") == "date" else (
            "textarea" if (prop.get("maxLength") or 0) > 200 else "text")
        return FieldSpec(key, "profile", type=kind, **common)
    if t == "number":
        kind = "inr" if leaf.endswith("_inr") else ("percent" if leaf.endswith("_pct")
                                                   else "number")
        return FieldSpec(key, "profile", type=kind, valuation=leaf in _VALUATION_PROFILE,
                         **common)
    if t == "integer":
        return FieldSpec(key, "profile", type="integer", **common)
    if t == "boolean":
        return FieldSpec(key, "profile", type="boolean", **common)
    if t == "array" and (prop.get("items") or {}).get("type") == "string":
        return FieldSpec(key, "profile", type="string_list", **common)
    return FieldSpec(key, "profile", type="json", **common)


_VALUATION_PROFILE = {"pre_money_inr", "post_money_inr", "enterprise_value_inr",
                      "equity_value_inr", "valuation_cap_inr"}


def profile_fields(schema: dict | None) -> list[FieldSpec]:
    """The class's deal-profile schema flattened one level: 'profile.tenor_months',
    'profile.security_package.primary'. Arrays of objects stay one 'json' field."""
    out: list[FieldSpec] = []
    for name, prop in ((schema or {}).get("properties") or {}).items():
        if prop.get("type") == "object" and prop.get("properties"):
            for sub, sub_prop in prop["properties"].items():
                spec = _profile_spec(f"{PROFILE_PREFIX}{name}.{sub}", sub_prop)
                parent = prop.get("title") or name
                out.append(FieldSpec(**{**spec.__dict__, "label": f"{parent} · {spec.label}"}))
        else:
            out.append(_profile_spec(f"{PROFILE_PREFIX}{name}", prop))
    return out


def specs_for(schema: dict | None) -> list[FieldSpec]:
    return [*BASE_FIELDS, *profile_fields(schema)]


def build_profile(values: dict[str, object], schema: dict | None) -> dict:
    """The deal profile object from 'profile.*' values (empty values left out)."""
    out: dict = {}
    for spec in profile_fields(schema):
        value = values.get(spec.key)
        if value is None or value == "" or value == []:
            continue
        path = spec.key[len(PROFILE_PREFIX):].split(".")
        target = out
        for part in path[:-1]:
            target = target.setdefault(part, {})
        target[path[-1]] = value
    return out


# ------------------------------------------------------------------------- normalisers

UNIT_FACTORS = {"crore": 10_000_000, "crores": 10_000_000, "cr": 10_000_000, "cr.": 10_000_000,
                "lakh": 100_000, "lakhs": 100_000, "lac": 100_000, "lacs": 100_000,
                "l": 100_000, "million": 1_000_000, "millions": 1_000_000, "mn": 1_000_000,
                "m": 1_000_000, "billion": 1_000_000_000, "bn": 1_000_000_000,
                "thousand": 1_000, "k": 1_000, "rupees": 1, "inr": 1}
_NUMBER = re.compile(r"\(?-?\s*[0-9][0-9,]*(?:\.[0-9]+)?\)?")
_UNIT_WORD = re.compile(r"\b(crores?|cr\.?|lakhs?|lacs?|million|mn|billion|bn|thousand)\b"
                        r"|(?<=[0-9])\s*(cr|l|k|m)\b", re.IGNORECASE)


def parse_number(raw: object) -> float | None:
    """'1,32,00,000' -> 13200000.0; '(3.42)' -> -3.42; '11.25%' -> 11.25. None when the text
    holds no number."""
    if isinstance(raw, bool) or raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    text = str(raw).strip().replace("−", "-").replace("–", "-")
    m = _NUMBER.search(text)
    if not m:
        return None
    token = m.group(0)
    negative = token.startswith("(") and token.endswith(")") or "-" in token
    digits = re.sub(r"[^0-9.]", "", token)
    if not digits or digits == ".":
        return None
    try:
        value = float(digits)
    except ValueError:
        return None
    return -value if negative else value


def unit_factor(text: str | None) -> int | None:
    if not text:
        return None
    m = _UNIT_WORD.search(text)
    if not m:
        return None
    word = (m.group(1) or m.group(2) or "").lower().rstrip(".")
    return UNIT_FACTORS.get(word)


def parse_inr(raw: object, unit: str | None = None) -> int | None:
    """An amount in whole rupees. '₹412.38 crore' -> 4123800000; 'INR 150 crore' ->
    1500000000; '12.5 L' -> 1250000; '1,00,000' -> 100000. A bare number is multiplied by
    `unit` ('crore', 'lakh', ...) when given; otherwise it is taken as rupees."""
    number = parse_number(raw)
    if number is None:
        return None
    factor = unit_factor(str(raw)) if isinstance(raw, str) else None
    if factor is None and unit:
        factor = UNIT_FACTORS.get(unit.lower().strip())
    return int(round(number * (factor or 1)))


def format_inr(value: int | float | None) -> str:
    """4123800000 -> '₹412.38 Cr'; 1250000 -> '₹12.50 L'."""
    if value is None:
        return "—"
    v = float(value)
    if abs(v) >= 10_000_000:
        return f"₹{v / 10_000_000:,.2f} Cr"
    if abs(v) >= 100_000:
        return f"₹{v / 100_000:,.2f} L"
    return f"₹{v:,.0f}"


_MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug",
                                       "sep", "oct", "nov", "dec"], start=1)}


def parse_date(raw: object) -> str | None:
    """ISO date from '2024-06-14', '14/06/2024' (day first, as in India), '14 June 2024',
    'June 14, 2024' or '14-Jun-2024'. None when no full date is present."""
    if raw is None:
        return None
    if isinstance(raw, (date, datetime)):
        return (raw.date() if isinstance(raw, datetime) else raw).isoformat()
    text = str(raw).strip()
    m = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", text)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    else:
        m = re.search(r"\b(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})\b", text)
        if m:
            d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        else:
            m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?[\s-]+([A-Za-z]{3,9})[\s,-]+(\d{4})\b",
                          text)
            if m and m.group(2)[:3].lower() in _MONTHS:
                d, mo, y = int(m.group(1)), _MONTHS[m.group(2)[:3].lower()], int(m.group(3))
            else:
                m = re.search(r"\b([A-Za-z]{3,9})\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b",
                              text)
                if not (m and m.group(1)[:3].lower() in _MONTHS):
                    return None
                mo, d, y = _MONTHS[m.group(1)[:3].lower()], int(m.group(2)), int(m.group(3))
    try:
        return date(y, mo, d).isoformat()
    except ValueError:
        return None


def parse_months(raw: object) -> int | None:
    """'60 months' -> 60, '5 years' -> 60, 60 -> 60."""
    number = parse_number(raw)
    if number is None:
        return None
    text = str(raw).lower() if isinstance(raw, str) else ""
    if re.search(r"\b(years?|yrs?)\b", text):
        number *= 12
    return int(round(number))


_CLASS_WORDS = {
    "DEBT": ("debt", "ncd", "debenture", "loan", "bond", "credit", "borrow"),
    "EQUITY": ("equity", "series", "pre-ipo", "growth round", "private equity"),
    "MNA": ("m&a", "mna", "acquisition", "merger", "buyout", "divest", "sale of"),
    "HYBRID": ("hybrid", "convertible", "ccps", "ccd", "mezzanine", "ocd"),
    "JV": ("jv", "joint venture"),
    "LPGP": ("lpgp", "lp/gp", "fund", "aif", "limited partner"),
    "ALLIANCE": ("alliance", "partnership", "licensing", "distribution"),
}


def normalise_enum(spec: FieldSpec, raw: object) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip()
    options = spec.options or ()
    for option in options:
        if text.lower() == option.lower():
            return option
    for option, label in (spec.enum_labels or {}).items():
        if text.lower() == str(label).lower():
            return option
    if spec.key == "transaction_class":
        low = text.lower()
        for cls, words in _CLASS_WORDS.items():
            if any(w in low for w in words):
                return cls
    simple = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    for option in options:
        if simple == option.lower():
            return option
    return None


def _clean_text(raw: object, max_length: int | None) -> str | None:
    if raw is None:
        return None
    text = " ".join(str(raw).split())
    if not text or text.lower() in ("null", "none", "n/a", "na", "not stated", "unknown", "-"):
        return None
    return text[:max_length] if max_length else text


def _bool(raw: object) -> bool | None:
    if isinstance(raw, bool):
        return raw
    if raw is None:
        return None
    text = str(raw).strip().lower()
    if text in ("true", "yes", "y", "1"):
        return True
    if text in ("false", "no", "n", "0"):
        return False
    return None


def _range_error(spec: FieldSpec, value: float) -> str | None:
    if spec.minimum is not None and value < spec.minimum:
        return f"{spec.label} must be at least {spec.minimum:g}"
    if spec.maximum is not None and value > spec.maximum:
        return f"{spec.label} must be at most {spec.maximum:g}"
    return None


def normalise_value(spec: FieldSpec, raw: object, unit: str | None = None
                    ) -> tuple[object, str | None]:
    """(value, error). The value is None when `raw` is empty or invalid; the error says why
    an invalid value was refused. Lists (parties, criteria, flags) are cleaned entry by
    entry; invalid entries are dropped."""
    t = spec.type
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None, None
    if t in ("text", "textarea"):
        return _clean_text(raw, spec.max_length), None
    if t == "identifier":
        try:
            return normalise_identifier(spec.scheme, str(raw).replace(" ", "")), None
        except RuleViolation:
            return None, f"Not a valid {spec.scheme.value}: {str(raw)[:40]!r}"
    if t == "inr":
        value = raw if isinstance(raw, int) and not isinstance(raw, bool) else parse_inr(raw, unit)
        if value is None:
            return None, f"Not an amount: {str(raw)[:40]!r}"
        return value, _range_error(spec, value)
    if t in ("number", "percent"):
        value = parse_number(raw)
        if value is None:
            return None, f"Not a number: {str(raw)[:40]!r}"
        value = round(value, 4)
        error = _range_error(spec, value)
        return (None if error else value), error
    if t == "integer":
        value = parse_months(raw) if spec.key.endswith("_months") else (
            None if parse_number(raw) is None else int(round(parse_number(raw))))
        if value is None:
            return None, f"Not a whole number: {str(raw)[:40]!r}"
        error = _range_error(spec, value)
        return (None if error else value), error
    if t == "date":
        value = parse_date(raw)
        if value is None:
            year = re.search(r"\b(19|20)\d{2}\b", str(raw))
            return None, (f"Only the year ({year.group(0)}) is stated; enter the full date"
                          if year else f"Not a date: {str(raw)[:40]!r}")
        return value, None
    if t == "enum":
        value = normalise_enum(spec, raw)
        return (value, None) if value else (None, f"Not one of the options: {str(raw)[:40]!r}")
    if t == "boolean":
        value = _bool(raw)
        return (value, None) if value is not None else (None, "Not yes or no")
    if t == "string_list":
        items = raw if isinstance(raw, list) else [raw]
        clean = [c for c in (_clean_text(i if not isinstance(i, dict) else
                                         i.get("name") or i.get("value"), 200)
                             for i in items) if c]
        return (clean or None), None
    if t == "parties":
        return (clean_parties(raw) or None), None
    if t == "flags":
        return (clean_flags(raw) or None), None
    if t == "criteria":
        return (clean_criteria(raw) or None), None
    return raw, None  # json: validated with the profile schema at confirm


def clean_parties(raw: object) -> list[dict]:
    out: list[dict] = []
    roles = {r.value for r in PartyRole}
    types = {p.value for p in PartyType}
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        name = _clean_text(item.get("name") or item.get("display_name"), 200)
        if not name:
            continue
        role = str(item.get("role") or "").strip().lower()
        role = role if role in roles else _guess_role(role)
        ptype = str(item.get("party_type") or "").strip().lower()
        ptype = ptype if ptype in types else _guess_party_type(name)
        identifiers = []
        for ident in item.get("identifiers") or []:
            if not isinstance(ident, dict):
                continue
            try:
                scheme = IdentifierScheme(str(ident.get("scheme", "")).upper())
                identifiers.append({"scheme": scheme.value, "value": normalise_identifier(
                    scheme, str(ident.get("value", "")).replace(" ", ""))})
            except (ValueError, RuleViolation):
                continue
        entry = {"name": name, "role": role, "party_type": ptype, "identifiers": identifiers,
                 "include": bool(item.get("include", True))}
        if not any(p["name"].lower() == name.lower() and p["role"] == role for p in out):
            out.append(entry)
    return out


def _guess_role(text: str) -> str:
    for word, role in (("lend", "lender"), ("bank", "lender"), ("invest", "investor"),
                       ("subscri", "investor"), ("buy", "buyer"), ("acquir", "buyer"),
                       ("sell", "seller"), ("vendor", "seller"), ("promot", "seller"),
                       ("target", "target"), ("issuer", "issuer"), ("borrow", "issuer"),
                       ("counsel", "counsel"), ("legal", "counsel"), ("law", "counsel"),
                       ("advis", "advisor"), ("arranger", "advisor"), ("trustee", "advisor"),
                       ("auditor", "advisor")):
        if word in text:
            return role
    return "advisor"


def _guess_party_type(name: str) -> str:
    low = name.lower()
    if re.search(r"\bllp\b", low):
        return "llp"
    if re.search(r"\bfund\b|\baif\b|capital partners", low):
        return "fund"
    if re.search(r"\btrust\b", low):
        return "trust"
    if re.search(r"limited|ltd|bank|corporation|inc\b|plc\b|gmbh|pte", low):
        return "company"
    if re.search(r"&\s*co\b|associates|partners", low):
        return "partnership"
    if len(name.split()) <= 4:
        return "individual"
    return "company"


def clean_flags(raw: object) -> list[dict]:
    out: list[dict] = []
    for item in raw if isinstance(raw, list) else []:
        if isinstance(item, str):
            item = {"flag": item}
        if not isinstance(item, dict):
            continue
        flag = re.sub(r"[^A-Z0-9]+", "_", str(item.get("flag") or "").upper()).strip("_")
        if flag in ("PN3", "PRESS_NOTE3", "PRESSNOTE_3"):
            flag = "PRESS_NOTE_3"
        if flag not in REGULATORY_FLAGS or any(f["flag"] == flag for f in out):
            continue
        out.append({"flag": flag, "reason": _clean_text(item.get("reason"), 300) or "",
                    "include": bool(item.get("include", True))})
    return out


def clean_criteria(raw: object) -> list[dict]:
    out: list[dict] = []
    ops = {o.value for o in CriterionOperator}
    hardness = {h.value for h in CriterionHardness}
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        key = re.sub(r"[^a-z0-9_]+", "_", str(item.get("criterion_key") or "").lower()).strip("_")
        op = str(item.get("operator") or "eq").lower()
        hard = str(item.get("hardness") or "soft").lower()
        if not key or op not in ops or hard not in hardness or item.get("value") in (None, ""):
            continue
        weight = item.get("weight")
        weight = float(weight) if isinstance(weight, (int, float)) and not isinstance(
            weight, bool) and 0 <= weight <= 1 else (0.5 if hard == "soft" else None)
        value = _criterion_value(op, item["value"])
        if value is None:
            # gte/lte on a word ('A-' rating) is a match on that word
            if op in ("gte", "lte") and isinstance(item["value"], str):
                op, value = "eq", item["value"].strip()[:100]
            else:
                continue
        out.append({"criterion_key": key[:100], "operator": op, "value": value,
                    "hardness": hard, "weight": weight,
                    "include": bool(item.get("include", True))})
    return out


def _criterion_value(op: str, value: object) -> object:
    """The value in the shape the mandate rules want (core.services.mandates), or None."""
    if op in ("gte", "lte"):
        n = parse_number(value) if isinstance(value, str) and re.fullmatch(
            r"\s*[0-9][0-9,]*(?:\.[0-9]+)?\s*", value) else value
        return n if isinstance(n, (int, float)) and not isinstance(n, bool) else None
    if op == "between":
        return value if isinstance(value, list) and len(value) == 2 else None
    if op in ("in", "not_in"):
        if isinstance(value, str) and value.strip():
            value = [v.strip() for v in value.split(",") if v.strip()]
        return value if isinstance(value, list) and value else None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) or (isinstance(value, str) and value.strip()):
        return value.strip() if isinstance(value, str) else value
    return None


def sanity_errors(values: dict[str, object]) -> dict[str, str]:
    """Cross-field checks on financials: EBITDA and PAT cannot exceed revenue."""
    errors: dict[str, str] = {}
    revenue = values.get("revenue_inr")
    if isinstance(revenue, (int, float)) and revenue > 0:
        for key, label in (("ebitda_inr", "EBITDA"), ("pat_inr", "Profit after tax")):
            v = values.get(key)
            if isinstance(v, (int, float)) and v > revenue:
                errors[key] = f"{label} is larger than revenue; check the column or unit"
        nd = values.get("net_debt_inr")
        if isinstance(nd, (int, float)) and abs(nd) > 20 * revenue:
            errors["net_debt_inr"] = "Net debt is over 20x revenue; check the unit"
    return errors


def same_value(spec: FieldSpec, a: object, b: object) -> bool:
    """Two candidate values for one field agree (0.5% tolerance for amounts, case and
    punctuation ignored for text)."""
    if a is None or b is None:
        return a is b
    if spec.type in ("inr", "number", "percent", "integer") and isinstance(a, (int, float)) \
            and isinstance(b, (int, float)):
        scale = max(abs(a), abs(b), 1)
        return abs(a - b) / scale <= 0.005
    if isinstance(a, str) and isinstance(b, str):
        ca, cb = canonical_text(a), canonical_text(b)
        if ca == cb:
            return True
        if spec.type in ("text", "textarea") and ca and cb:
            # Free text read from two documents agrees when one wording holds the other or
            # the shorter one's words nearly all appear in the other (a paraphrase is not a conflict).
            if ca in cb or cb in ca:
                return True
            wa, wb = set(ca.split()), set(cb.split())
            return len(wa & wb) / max(1, min(len(wa), len(wb))) >= 0.8
        return False
    return a == b


def canonical_text(text: str) -> str:
    low = text.lower()
    low = re.sub(r"\bpvt\.?\b", "private", low)
    low = re.sub(r"\bltd\.?\b", "limited", low)
    low = re.sub(r"\bm/s\.?\s*", "", low)
    return re.sub(r"[^a-z0-9]+", " ", low).strip()


def display_value(spec: FieldSpec, value: object) -> str:
    if value is None:
        return "—"
    if spec.type == "inr":
        return format_inr(value)
    if spec.type == "percent":
        return f"{value:g}%"
    if spec.type in ("parties",):
        return ", ".join(p.get("name", "") for p in value)
    if spec.type == "flags":
        return ", ".join(f.get("flag", "") for f in value)
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    if spec.type == "enum" and spec.enum_labels:
        return str(spec.enum_labels.get(value, value))
    return str(value)
