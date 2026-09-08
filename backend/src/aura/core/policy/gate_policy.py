"""Deterministic approval-gate classification. Never model-decided."""
from aura.core.domain.enums import ActionCategory

TOOL_CATEGORIES: dict[str, ActionCategory] = {
    "send_email": ActionCategory.OUTBOUND,
    "send_whatsapp": ActionCategory.OUTBOUND,
    "send_linkedin_message": ActionCategory.OUTBOUND,
    "create_invoice": ActionCategory.MONEY,
    "issue_refund": ActionCategory.MONEY,
    "record_payment": ActionCategory.MONEY,
    "draft_nda": ActionCategory.LEGAL,
    "draft_term_sheet": ActionCategory.LEGAL,
    "send_contract": ActionCategory.LEGAL,
    "get_deal_status": ActionCategory.INTERNAL_READ,
    "list_deals": ActionCategory.INTERNAL_READ,
    "search_notes": ActionCategory.INTERNAL_READ,
    "update_task_status": ActionCategory.INTERNAL_WRITE,
    "add_internal_note": ActionCategory.INTERNAL_WRITE,
}

_UNGATED = frozenset({ActionCategory.INTERNAL_READ, ActionCategory.INTERNAL_WRITE})


def classify(tool_name: str) -> ActionCategory:
    """Map a tool name to its action category. Unmapped tools are UNKNOWN."""
    return TOOL_CATEGORIES.get(tool_name, ActionCategory.UNKNOWN)


def requires_approval(category: ActionCategory) -> bool:
    """Default-deny: anything not explicitly internal requires human approval."""
    return category not in _UNGATED
