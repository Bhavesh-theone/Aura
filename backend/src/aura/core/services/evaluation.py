"""Evaluation scoring and online feedback (harness category 10). Pure functions.

Offline: golden-set scores per capability (accuracy and macro-F1 for classification, per-field
tolerance for extraction, a deterministic rubric for drafts), mean confidence, and calibration
(how often the model is right when it claims >= 0.95).

Online: the override rate from resolved handoffs, per capability, over a trailing window. A
person overriding the agent means: classify 'keep' when the agent proposed a different class,
extraction 'discard', draft 'reject'. Accepting means 'confirm', 'verify', 'approve' (and
'keep' when the agent proposed keeping the class).
"""
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from aura.core.domain.enums import HandoffDirection
from aura.core.domain.handoff import Handoff

CALIBRATION_CONFIDENCE = 0.95
FIGURES = ("revenue_inr", "ebitda_inr", "net_debt_inr")
OVERRIDE_WINDOW = timedelta(days=30)

# capability -> (override decision, accept decision)
OVERRIDE_DECISIONS = {"classify_document": ("keep", "confirm"),
                      "extract_financials": ("discard", "verify"),
                      "draft_email": ("reject", "approve")}


def aware(value: datetime | None) -> datetime | None:
    """SQLite hands back naive datetimes; they are UTC."""
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


# ------------------------------------------------------------------ classification

def classification_metrics(rows: list[tuple[str, str, float | None]]) -> dict:
    """rows: (expected, predicted, confidence)."""
    n = len(rows)
    correct = sum(1 for e, p, _ in rows if e == p)
    labels = sorted({e for e, _, _ in rows} | {p for _, p, _ in rows})
    f1s = []
    for label in labels:
        tp = sum(1 for e, p, _ in rows if e == label and p == label)
        fp = sum(1 for e, p, _ in rows if e != label and p == label)
        fn = sum(1 for e, p, _ in rows if e == label and p != label)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1s.append(2 * precision * recall / (precision + recall) if precision + recall else 0.0)
    return {"accuracy": round(correct / n, 4) if n else 0.0,
            "macro_f1": round(sum(f1s) / len(f1s), 4) if f1s else 0.0,
            **confidence_metrics([(c, e == p) for e, p, c in rows])}


def confidence_metrics(rows: list[tuple[float | None, bool]]) -> dict:
    """rows: (confidence, correct). Calibration = accuracy in the >= 0.95 bucket."""
    known = [(c, ok) for c, ok in rows if isinstance(c, (int, float))]
    confident = [ok for c, ok in known if c >= CALIBRATION_CONFIDENCE]
    return {"mean_confidence": round(sum(c for c, _ in known) / len(known), 4) if known
            else None,
            "calibration": {"confidence_at_least": CALIBRATION_CONFIDENCE,
                            "n": len(confident),
                            "accuracy": round(sum(confident) / len(confident), 4)
                            if confident else None}}


# ------------------------------------------------------------------ extraction

def within_tolerance(expected: float | None, actual: float | None, tolerance: dict) -> bool:
    if expected is None or actual is None:
        return expected is None and actual is None
    allowed = max(float(tolerance.get("abs", 0)), float(tolerance.get("rel", 0)) * abs(expected))
    return abs(actual - expected) <= allowed


def score_extraction(expected: dict, actual: dict, tolerance: dict) -> dict:
    fields = {k: within_tolerance(expected.get(k), actual.get(k), tolerance) for k in FIGURES}
    return {"fields": fields, "passed": all(fields.values()),
            "score": round(sum(fields.values()) / len(fields), 4)}


def extraction_metrics(cases: list[dict]) -> dict:
    """cases: {"fields": {...}, "passed": bool, "confidence": float|None}."""
    n = len(cases)
    per_field = {k: round(sum(1 for c in cases if c["fields"][k]) / n, 4) if n else 0.0
                 for k in FIGURES}
    return {"case_accuracy": round(sum(1 for c in cases if c["passed"]) / n, 4) if n else 0.0,
            "field_accuracy": per_field,
            **confidence_metrics([(c.get("confidence"), c["passed"]) for c in cases])}


# ------------------------------------------------------------------ draft rubric

_AMOUNT = re.compile(
    r"(?:₹|\bINR|\bRs\.?)\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*(crore|cr|lakhs?|lacs?|mn|million|"
    r"bn|billion)?\b|\b([0-9][0-9,]*(?:\.[0-9]+)?)\s*(crore|cr|lakhs?|lacs?|million|bn|"
    r"billion)\b|([0-9]+(?:\.[0-9]+)?)\s*%", re.IGNORECASE)
_COMMITMENT = re.compile(
    r"\bwe (?:hereby )?(?:guarantee|promise|assure you|commit to|will ensure|undertake)\b|"
    r"\bguaranteed\b|\brisk[- ]free\b|\bassured returns?\b|\bcertain(?:ly)? to close\b|"
    r"\bno risk\b", re.IGNORECASE)


def amounts(text: str) -> set[str]:
    """Money amounts and percentages, normalised ('60 cr', '1250000', '12.5%')."""
    found = set()
    for m in _AMOUNT.finditer(text or ""):
        number = (m.group(1) or m.group(3) or m.group(5) or "").replace(",", "")
        unit = (m.group(2) or m.group(4) or ("%" if m.group(5) else "")).lower()
        unit = {"crore": "cr", "lakh": "lakh", "lakhs": "lakh", "lac": "lakh", "lacs": "lakh",
                "million": "mn", "billion": "bn"}.get(unit, unit)
        try:
            number = f"{float(number):g}"
        except ValueError:
            continue
        found.add(f"{number} {unit}".strip())
    return found


def score_draft(subject: str, body: str, case: dict) -> dict:
    """Deterministic rubric for a drafted email. Every rule must hold for the case to pass."""
    party = (case.get("party") or {}).get("display_name", "")
    deal = case.get("deal") or {}
    allowed = amounts(case.get("brief", "")) | amounts(deal.get("name", ""))
    words = len(re.findall(r"\S+", body or ""))
    invented = sorted(amounts(f"{subject}\n{body}") - allowed)
    first_name = party.split()[0] if party else ""
    rules = {
        "has_subject": bool((subject or "").strip()),
        "mentions_party": bool(party) and (party.lower() in (body or "").lower()
                                           or first_name.lower() in (body or "").lower()),
        "under_word_limit": 0 < words <= int(case.get("max_words", 200)),
        "no_invented_amounts": not invented,
        "no_commitment_language": not _COMMITMENT.search(f"{subject}\n{body}"),
    }
    return {"rules": rules, "passed": all(rules.values()), "words": words,
            "invented_amounts": invented,
            "score": round(sum(rules.values()) / len(rules), 4)}


def draft_metrics(cases: list[dict]) -> dict:
    n = len(cases)
    rule_names = list(cases[0]["rules"]) if cases else []
    return {"rubric_pass_rate": round(sum(1 for c in cases if c["passed"]) / n, 4) if n else 0.0,
            "rule_pass_rate": {r: round(sum(1 for c in cases if c["rules"][r]) / n, 4)
                               for r in rule_names},
            **confidence_metrics([(c.get("confidence"), c["passed"]) for c in cases])}


# ------------------------------------------------------------------ online feedback

@dataclass
class OverrideRate:
    capability: str
    decisions: int
    overrides: int
    rate: float | None
    window_days: int


def _is_override(h: Handoff) -> bool | None:
    pair = OVERRIDE_DECISIONS.get(h.task_type or "")
    decision = (h.directive or {}).get("decision")
    if pair is None or decision not in pair:
        return None
    if h.task_type == "classify_document" and decision == "keep":
        args = (h.context_package.get("proposed_action") or {}).get("arguments") or {}
        return args.get("proposed_class") != args.get("current_class")
    return decision == pair[0]


def override_rates(handoffs: list[Handoff], now: datetime,
                   window: timedelta = OVERRIDE_WINDOW,
                   since: dict[str, datetime | None] | None = None) -> dict[str, OverrideRate]:
    """Per capability over resolved bot-to-human handoffs in the window. `since` limits a
    capability to decisions made after a moment (after its last demotion)."""
    now = aware(now)
    start = now - window
    counts = {c: [0, 0] for c in OVERRIDE_DECISIONS}
    for h in handoffs:
        resolved_at = aware(h.resolved_at)
        if h.direction is not HandoffDirection.BOT_TO_HUMAN or resolved_at is None \
                or resolved_at < start or resolved_at > now:
            continue
        floor = aware((since or {}).get(h.task_type or ""))
        if floor is not None and resolved_at <= floor:
            continue
        verdict = _is_override(h)
        if verdict is None:
            continue
        counts[h.task_type][0] += 1
        counts[h.task_type][1] += int(verdict)
    return {c: OverrideRate(c, d, o, round(o / d, 4) if d else None, window.days)
            for c, (d, o) in counts.items()}
