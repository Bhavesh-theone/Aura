"""SOSPE I7 / section 9.5: what a handoff must contain, and the package builder for gates."""
from datetime import datetime, timedelta, timezone

from aura.core.domain.enums import ActionCategory
from aura.core.domain.errors import RuleViolation
from aura.core.domain.segment import ProposedAction
from aura.core.policy.gate_policy import (DEFAULT_MATERIALITY_CAP_INR, exceeds_materiality,
                                          recommendation)

MIN_QUESTION_CHARS = 15
MIN_CONSEQUENCE_CHARS = 25
MIN_REASONING_CHARS = 30
MIN_OPTIONS, MAX_OPTIONS = 2, 5
DEFAULT_ESCALATION = timedelta(hours=24)
ESCALATES_TO_ROLE = "dealmaker"

# Decisions that let the job carry on; any other decision ends it.
APPROVING_DECISIONS = frozenset({"approve", "confirm", "verify"})


def _text(value, path: str, min_len: int = 1) -> str:
    if not isinstance(value, str) or len(value.strip()) < min_len:
        raise RuleViolation(f"{path} must be a string of at least {min_len} characters")
    return value


def _mapping(value, path: str) -> dict:
    if not isinstance(value, dict):
        raise RuleViolation(f"{path} is required and must be an object")
    return value


def parse_timestamp(value, path: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(_text(value, path).replace("Z", "+00:00"))
    except ValueError:
        raise RuleViolation(f"{path} must be an ISO-8601 timestamp") from None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def validate_bot_to_human(package) -> datetime:
    """Raise RuleViolation unless the context package is complete. Returns the
    auto_escalate_at timestamp."""
    package = _mapping(package, "context_package")
    decision = _mapping(package.get("decision_required"), "decision_required")
    _text(decision.get("question"), "decision_required.question", MIN_QUESTION_CHARS)

    options = decision.get("options")
    if not isinstance(options, list) or not MIN_OPTIONS <= len(options) <= MAX_OPTIONS:
        raise RuleViolation(
            f"decision_required.options must be a list of {MIN_OPTIONS} to {MAX_OPTIONS} items")
    ids = []
    for i, option in enumerate(options):
        where = f"decision_required.options[{i}]"
        option = _mapping(option, where)
        ids.append(_text(option.get("id"), f"{where}.id"))
        _text(option.get("label"), f"{where}.label")
        _text(option.get("consequence"), f"{where}.consequence")
        if not isinstance(option.get("reversible"), bool):
            raise RuleViolation(f"{where}.reversible must be true or false")
    if len(set(ids)) != len(ids):
        raise RuleViolation("decision_required.options ids must be unique")
    if decision.get("recommendation") not in ids:
        raise RuleViolation("decision_required.recommendation must equal one of the option ids")
    confidence = decision.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) \
            or not 0 <= confidence <= 1:
        raise RuleViolation("decision_required.confidence must be a number from 0 to 1")

    nothing = _mapping(package.get("if_you_do_nothing"), "if_you_do_nothing")
    _text(nothing.get("consequence"), "if_you_do_nothing.consequence", MIN_CONSEQUENCE_CHARS)
    _text(nothing.get("escalates_to_role"), "if_you_do_nothing.escalates_to_role")
    escalate_at = parse_timestamp(nothing.get("auto_escalate_at"),
                                  "if_you_do_nothing.auto_escalate_at")

    for key in ("what_happened", "evidence"):
        if not isinstance(package.get(key), list):
            raise RuleViolation(f"{key} is required and must be a list")
    return escalate_at


def option_ids(package: dict) -> list[str]:
    return [o["id"] for o in package.get("decision_required", {}).get("options", [])]


def validate_directive(directive) -> dict:
    """SOSPE 9.5.1: decision, reasoning, new_constraints.do_not_revisit, next_checkpoint."""
    directive = _mapping(directive, "directive")
    _text(directive.get("decision"), "directive.decision")
    _text(directive.get("reasoning"), "directive.reasoning", MIN_REASONING_CHARS)
    constraints = _mapping(directive.get("new_constraints"), "directive.new_constraints")
    if not isinstance(constraints.get("do_not_revisit"), list):
        raise RuleViolation("directive.new_constraints.do_not_revisit must be a list")
    checkpoint = _mapping(directive.get("next_checkpoint"), "directive.next_checkpoint")
    _text(checkpoint.get("condition"), "directive.next_checkpoint.condition")
    _text(checkpoint.get("escalate_if"), "directive.next_checkpoint.escalate_if")
    return directive


def _options_for(action: ProposedAction) -> list[dict]:
    if action.tool == "classify_document":
        proposed = action.arguments.get("proposed_class", "the proposed class")
        current = action.arguments.get("current_class", "the current class")
        return [
            {"id": "confirm", "label": f"Confirm {proposed}", "reversible": True,
             "consequence": f"The document is recorded as {proposed} and marked confirmed."},
            {"id": "keep", "label": f"Keep {current}", "reversible": True,
             "consequence": f"The document stays {current}; the proposal is discarded."},
        ]
    if action.tool == "extract_financials":
        return [
            {"id": "verify", "label": "Verify the extraction", "reversible": True,
             "consequence": "The figures are marked human-verified and may feed a valuation."},
            {"id": "discard", "label": "Discard it", "reversible": True,
             "consequence": "The extraction stays on record but never feeds a valuation."},
        ]
    return [
        {"id": "approve", "label": "Approve", "reversible": False,
         "consequence": "The job continues with this action. Nothing is sent automatically."},
        {"id": "reject", "label": "Reject", "reversible": True,
         "consequence": "The job ends here and the proposed action is discarded."},
    ]


def _confidence(action: ProposedAction) -> float:
    value = action.arguments.get("confidence")
    if isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= 1:
        return float(value)
    return 0.5


def build_gate_package(action: ProposedAction, now: datetime,
                       cap_inr: int = DEFAULT_MATERIALITY_CAP_INR,
                       escalate_after: timedelta = DEFAULT_ESCALATION) -> dict:
    """A valid bot_to_human context package for a gated tool call, built from the proposed
    action alone. The recommendation comes from gate_policy, not from the model."""
    options = _options_for(action)
    if action.tool == "classify_document":
        recommended = ("confirm" if action.arguments.get("proposed_class")
                       != action.arguments.get("current_class") else "keep")
    elif action.tool == "extract_financials":
        recommended = "discard"
    else:
        recommended = recommendation(action.category, action.materiality_inr, cap_inr)
    escalate_at = (now + escalate_after).isoformat()
    what_happened = [f"The agent proposed the action '{action.tool}'.", action.summary]
    if exceeds_materiality(action.materiality_inr, cap_inr):
        what_happened.append(
            f"Its value of INR {action.materiality_inr:,} is above the INR {cap_inr:,} cap, "
            "so it is draft-only and a human must decide.")
    elif action.category is ActionCategory.UNKNOWN:
        what_happened.append("The tool is not mapped in the gate policy, so it is gated.")
    return {
        "what_happened": what_happened,
        "evidence": [{"type": "proposed_action", "tool": action.tool,
                      "category": action.category.value, "arguments": action.arguments}],
        "decision_required": {
            "question": f"Decide on the proposed action: {action.summary}"[:300],
            "options": options,
            "recommendation": recommended,
            "confidence": _confidence(action),
        },
        "if_you_do_nothing": {
            "consequence": f"Job stays paused; escalates to {ESCALATES_TO_ROLE} at "
                           f"{(now + escalate_after).strftime('%d %b %Y %H:%M UTC')}.",
            "auto_escalate_at": escalate_at,
            "escalates_to_role": ESCALATES_TO_ROLE,
        },
        "proposed_action": {"tool": action.tool, "category": action.category.value,
                            "arguments": action.arguments, "summary": action.summary,
                            "materiality_inr": action.materiality_inr},
    }
