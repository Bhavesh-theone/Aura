import re

from aura.core.domain.enums import IdentifierScheme
from aura.core.domain.errors import RuleViolation

_PATTERNS = {
    IdentifierScheme.PAN: r"^[A-Z]{5}[0-9]{4}[A-Z]$",
    IdentifierScheme.GSTIN: r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]{3}$",
    IdentifierScheme.DIN: r"^[0-9]{8}$",
    IdentifierScheme.CIN: r"^[LUu][0-9]{5}[A-Za-z]{2}[0-9]{4}[A-Za-z]{3}[0-9]{6}$",
    IdentifierScheme.LLPIN: r"^[A-Z]{3}-[0-9]{4}$",
}


def normalise_identifier(scheme: IdentifierScheme, value: str) -> str:
    """Strip and upper-case, then validate against the scheme's format."""
    clean = value.strip().upper()
    if not re.match(_PATTERNS[scheme], clean):
        raise RuleViolation(f"Invalid {scheme.value} format: {value!r}")
    return clean
