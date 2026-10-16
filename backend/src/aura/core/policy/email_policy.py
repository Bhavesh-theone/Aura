"""Email address rules: one normal form, so a contact, a suppression entry and an outbound
recipient compare equal whenever they name the same mailbox."""
import re

from aura.core.domain.errors import RuleViolation

# Deliberately plain: local@domain.tld, no spaces, no display names, no quoting.
_EMAIL = re.compile(r"^[a-z0-9._%+'-]+@[a-z0-9-]+(\.[a-z0-9-]+)*\.[a-z]{2,}$")
_DOMAIN = re.compile(r"^[a-z0-9-]+(\.[a-z0-9-]+)*\.[a-z]{2,}$")
MAX_EMAIL = 254


def normalise_email(value) -> str:
    """Trimmed and lower-cased. Raises RuleViolation (422) unless it is a plain address."""
    email = value.strip().lower() if isinstance(value, str) else ""
    if not email or len(email) > MAX_EMAIL or not _EMAIL.match(email) or ".." in email:
        raise RuleViolation("email must be a plain address such as name@example.com")
    return email


def normalise_domain(value) -> str:
    domain = value.strip().lower().lstrip("@") if isinstance(value, str) else ""
    if not domain or len(domain) > MAX_EMAIL or not _DOMAIN.match(domain) or ".." in domain:
        raise RuleViolation("domain must look like example.com")
    return domain


def domain_of(email: str) -> str:
    return email.rsplit("@", 1)[-1].lower() if "@" in email else ""
