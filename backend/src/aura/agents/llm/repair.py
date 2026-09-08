"""Recover structured output from a small local model.

A 1.5B model on CPU emits malformed tool-call JSON routinely. Per
ARCHITECTURE.md section 2 rule 3, repair is a first-class component.
"""
import json
import re

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def _try_load(candidate: str) -> dict | None:
    try:
        value = json.loads(candidate)
    except (json.JSONDecodeError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def _repair(candidate: str) -> str:
    candidate = re.sub(r",\s*([}\]])", r"\1", candidate)  # trailing commas
    if '"' not in candidate and "'" in candidate:
        candidate = candidate.replace("'", '"')  # single-quoted keys/values
    return candidate


def _balanced_objects(text: str) -> list[str]:
    """Yield every balanced {...} span, outermost first."""
    spans, depth, start = [], 0, None
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth:
            depth -= 1
            if depth == 0 and start is not None:
                spans.append(text[start:i + 1])
    return spans


def extract_json(text: str) -> dict | None:
    """Best-effort extraction of a JSON object from model output."""
    if not text:
        return None

    candidates: list[str] = []
    candidates.extend(m.strip() for m in _FENCE.findall(text))
    candidates.append(text.strip())
    candidates.extend(_balanced_objects(text))

    for candidate in candidates:
        parsed = _try_load(candidate) or _try_load(_repair(candidate))
        if parsed is not None:
            return parsed
    return None
