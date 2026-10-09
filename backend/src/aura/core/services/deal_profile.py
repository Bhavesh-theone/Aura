"""Deal profiles: class-specific deal terms, validated by JSON Schema (draft 2020-12).

The schemas live next to the code in aura/core/schemas/deal_profile/<CLASS>.v<N>.json, one
per transaction class and version. A new deal starts with an empty profile, which every
schema accepts."""
import copy
import json
import re
from functools import cache
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from aura.core.clock import utcnow
from aura.core.domain.audit import AuditEntry
from aura.core.domain.deal import Deal
from aura.core.domain.enums import Role, TransactionClass
from aura.core.domain.errors import NotFound, RuleViolation
from aura.core.policy.rbac_policy import Capability, require
from aura.core.ports.repositories import AuditRepository, DealRepository

CURRENT_PROFILE_VERSION = 1
SCHEMA_DIR = Path(__file__).resolve().parent.parent / "schemas" / "deal_profile"
_FILENAME = re.compile(r"^(?P<cls>[A-Z]+)\.v(?P<version>\d+)\.json$")


@cache
def _schemas() -> dict[tuple[TransactionClass, int], dict]:
    found: dict[tuple[TransactionClass, int], dict] = {}
    for path in sorted(SCHEMA_DIR.glob("*.json")):
        m = _FILENAME.match(path.name)
        if m is None:
            continue
        schema = json.loads(path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        found[(TransactionClass(m["cls"]), int(m["version"]))] = schema
    return found


@cache
def _validator(transaction_class: TransactionClass, version: int) -> Draft202012Validator:
    return Draft202012Validator(_schemas()[(transaction_class, version)],
                                format_checker=FormatChecker())


def _class(transaction_class: TransactionClass | str) -> TransactionClass:
    try:
        return TransactionClass(transaction_class)
    except ValueError:
        raise NotFound(f"No deal profile schema for transaction class {transaction_class}") \
            from None


def list_schemas(version: int | None = None) -> dict[str, dict]:
    """The schema of every transaction class at `version` (default: current), by class."""
    v = version or CURRENT_PROFILE_VERSION
    return {cls.value: copy.deepcopy(s) for (cls, ver), s in _schemas().items() if ver == v}


def get_schema(transaction_class: TransactionClass | str, version: int | None = None) -> dict:
    """One class's schema. NotFound (404) for an unknown class or version."""
    cls, v = _class(transaction_class), version or CURRENT_PROFILE_VERSION
    schema = _schemas().get((cls, v))
    if schema is None:
        raise NotFound(f"No deal profile schema for {cls.value} version {v}")
    return copy.deepcopy(schema)


def _path(error) -> str:
    return "profile" + "".join(f"[{p}]" if isinstance(p, int) else f".{p}"
                               for p in error.absolute_path)


def validate_profile(transaction_class: TransactionClass, version: int | None,
                     profile: object) -> None:
    """Raise RuleViolation (422) unless `profile` is valid for the class at `version`
    (default: current). The message lists every problem as `path: message`."""
    v = version or CURRENT_PROFILE_VERSION
    cls = TransactionClass(transaction_class)
    if (cls, v) not in _schemas():
        raise RuleViolation(f"Unknown deal profile schema version {v} for {cls.value}")
    if not isinstance(profile, dict):
        raise RuleViolation("profile must be a JSON object")
    errors = sorted(_validator(cls, v).iter_errors(profile),
                    key=lambda e: (list(map(str, e.absolute_path)), e.message))
    if errors:
        raise RuleViolation(f"Invalid {cls.value} deal profile (v{v}): "
                            + "; ".join(f"{_path(e)}: {e.message}" for e in errors))


def changed_keys(before: dict, after: dict) -> list[str]:
    """Top-level keys added, removed or changed."""
    missing = object()
    return sorted(k for k in before.keys() | after.keys()
                  if before.get(k, missing) != after.get(k, missing))


def update_deal_profile(deal_id: int, profile: dict, actor: str, actor_role: Role,
                        deals: DealRepository, audit: AuditRepository,
                        profile_schema_version: int | None = None) -> Deal:
    """Replace a deal's profile (dealmaker or analyst), validated against its class."""
    require(actor_role, Capability.EDIT_DEAL_PROFILE, "edit a deal's profile")
    deal = deals.get(deal_id)
    if deal is None:
        raise NotFound("Deal not found")
    version = profile_schema_version or CURRENT_PROFILE_VERSION
    validate_profile(deal.transaction_class, version, profile)
    before = dict(deal.profile)
    deal.profile, deal.profile_schema_version = copy.deepcopy(profile), version
    saved = deals.update(deal)
    audit.append(AuditEntry(id=None, job_id=None, deal_id=deal_id, actor=actor,
                            action="deal_profile_updated", created_at=utcnow(),
                            payload={"profile_schema_version": version,
                                     "changed_keys": changed_keys(before, saved.profile)}))
    return saved
