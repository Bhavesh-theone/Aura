"""Rupee formatting for people: Indian digit grouping (12,34,56,789) and lakh / crore.

Machine formats (JSON, CSV) carry whole rupees as integers; these helpers are for the human
renderings (PDF, Word, on-screen). Pure: no I/O."""
from decimal import ROUND_HALF_UP, Decimal

RUPEE = "₹"
LAKH = 100_000
CRORE = 10_000_000


def to_inr_int(value: object) -> int | None:
    """Whole rupees, rounded half up; None for None or anything that is not a number."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(Decimal(str(value)).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    except (ArithmeticError, ValueError):
        return None


def group_indian(n: int) -> str:
    """12345678 -> '1,23,45,678' (last three digits, then pairs)."""
    sign, digits = ("-", str(-n)) if n < 0 else ("", str(n))
    if len(digits) <= 3:
        return sign + digits
    head, tail = digits[:-3], digits[-3:]
    pairs = []
    while len(head) > 2:
        pairs.insert(0, head[-2:])
        head = head[:-2]
    if head:
        pairs.insert(0, head)
    return sign + ",".join(pairs + [tail])


def format_inr(value: object, symbol: str = RUPEE) -> str:
    """'₹1,23,45,678' (whole rupees, Indian grouping); '' for no value."""
    n = to_inr_int(value)
    if n is None:
        return ""
    return f"-{symbol}{group_indian(-n)}" if n < 0 else f"{symbol}{group_indian(n)}"


def format_inr_compact(value: object, symbol: str = RUPEE) -> str:
    """'₹48.50 Cr', '₹4.20 L', '₹86,400'; '' for no value."""
    n = to_inr_int(value)
    if n is None:
        return ""
    sign, a = ("-", -n) if n < 0 else ("", n)
    if a >= CRORE:
        return f"{sign}{symbol}{_two(a / CRORE)} Cr"
    if a >= LAKH:
        return f"{sign}{symbol}{_two(a / LAKH)} L"
    return f"{sign}{symbol}{group_indian(a)}"


def _two(x: float) -> str:
    whole, frac = f"{x:.2f}".split(".")
    return f"{group_indian(int(whole))}.{frac}"
