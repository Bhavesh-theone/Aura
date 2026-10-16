"""What every renderer shares: human cell formatting, file names, the rendered-file type."""
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from aura.core.money import format_inr_compact, group_indian

IST = timezone(timedelta(hours=5, minutes=30), "IST")


@dataclass
class RenderedExport:
    content: bytes
    media_type: str
    extension: str


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def human_datetime(value: str | None) -> str:
    """ISO UTC -> '13 Oct 2026, 14:05' in IST."""
    dt = parse_iso(value)
    return dt.astimezone(IST).strftime("%d %b %Y, %H:%M") if dt else (value or "")


def human_date(value: str | None) -> str:
    dt = parse_iso(value)
    return dt.astimezone(IST).strftime("%d %b %Y") if dt else (value or "")


def human_cell(value, col_type: str) -> str:
    """One cell as a person reads it: rupees in lakh / crore, dates in IST, Yes / No."""
    if value is None or value == "":
        return "—" if col_type in ("inr", "int", "float", "pct", "date", "datetime") else ""
    if col_type == "inr":
        return format_inr_compact(value)
    if col_type == "int" and isinstance(value, (int, float)):
        return group_indian(int(value))
    if col_type == "float" and isinstance(value, (int, float)):
        return f"{value:,.2f}".rstrip("0").rstrip(".")
    if col_type == "pct" and isinstance(value, (int, float)):
        return f"{value * 100 if value <= 1 else value:.0f}%"
    if col_type == "datetime":
        return human_datetime(value)
    if col_type == "date":
        return human_date(value)
    if col_type == "bool":
        return "Yes" if value else "No"
    if col_type == "enum":
        return humanize(str(value))
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value)
    if isinstance(value, dict):
        return ", ".join(f"{k}: {v}" for k, v in value.items())
    return str(value)


ACRONYMS = re.compile(r"\b(nda|spa|shpa|gst|cin|pan|gstin|din|llpin|upsi|cp|mac|inr|ebitda|"
                      r"rbi|sebi|cci|fema|huf|llp|jv|mna|lpgp|moa|aoa|ipo|ncd)\b", re.I)


def humanize(value: str | None) -> str:
    """'red_flag' -> 'Red flag', 'BID_AUCTION' -> 'Bid auction', 'spa' -> 'SPA'."""
    if not value:
        return ""
    if value == "moa_aoa":
        return "MOA / AOA"
    text = value.replace("_", " ").replace("-", " ")
    text = text[:1].upper() + text[1:].lower()
    return ACRONYMS.sub(lambda m: m.group(0).upper(), text)


def slug(text: str, limit: int = 60) -> str:
    """'Project Kaveri (Sell-side)' -> 'Project-Kaveri-Sell-side'."""
    s = re.sub(r"[^A-Za-z0-9]+", "-", text or "").strip("-")
    return s[:limit].rstrip("-") or "deal"


def deal_filename(external_id: str, name: str, generated_at: str, extension: str) -> str:
    day = (parse_iso(generated_at) or datetime.now(timezone.utc)).astimezone(IST).date()
    return f"{slug(external_id, 32)}_{slug(name)}_{day.isoformat()}.{extension}"


def list_filename(generated_at: str, extension: str) -> str:
    day = (parse_iso(generated_at) or datetime.now(timezone.utc)).astimezone(IST).date()
    return f"Aura_deals_{day.isoformat()}.{extension}"
