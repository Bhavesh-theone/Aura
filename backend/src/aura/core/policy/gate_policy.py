"""Deterministic approval-gate classification. Never model-decided."""
from aura.core.domain.enums import ActionCategory

# 5 crore rupees. Anything above this is draft-only (autonomy level L1): a human acts.
DEFAULT_MATERIALITY_CAP_INR = 50_000_000

TOOL_CATEGORIES: dict[str, ActionCategory] = {
    "send_email": ActionCategory.OUTBOUND,
    "draft_email": ActionCategory.OUTBOUND,
    "send_whatsapp": ActionCategory.OUTBOUND,
    "send_linkedin_message": ActionCategory.OUTBOUND,
    # The Gmail MCP server's tools (aura.mcp.servers.gmail_server). The crew is never given
    # them; they are mapped so that anything reaching them through a gate is held.
    "create_gmail_draft": ActionCategory.OUTBOUND,
    "send_gmail": ActionCategory.OUTBOUND,
    "create_invoice": ActionCategory.MONEY,
    "issue_refund": ActionCategory.MONEY,
    "record_payment": ActionCategory.MONEY,
    "draft_nda": ActionCategory.LEGAL,
    "draft_term_sheet": ActionCategory.LEGAL,
    "send_contract": ActionCategory.LEGAL,
    "classify_document": ActionCategory.DOCUMENT_CLASSIFICATION,
    "extract_financials": ActionCategory.DOCUMENT_CLASSIFICATION,
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


def exceeds_materiality(materiality_inr: int | float | None,
                        cap_inr: int = DEFAULT_MATERIALITY_CAP_INR) -> bool:
    """True when the action's rupee value is strictly above the cap."""
    return materiality_inr is not None and materiality_inr > cap_inr


def requires_approval(category: ActionCategory, materiality_inr: int | float | None = None,
                      cap_inr: int = DEFAULT_MATERIALITY_CAP_INR) -> bool:
    """Default-deny: anything not explicitly internal requires human approval, and so
    does anything above the materiality cap, whatever its category."""
    return exceeds_materiality(materiality_inr, cap_inr) or category not in _UNGATED


def recommendation(category: ActionCategory, materiality_inr: int | float | None = None,
                   cap_inr: int = DEFAULT_MATERIALITY_CAP_INR) -> str:
    """The policy's suggested option for a gated action: unmapped tools and over-cap
    amounts are not something to wave through."""
    if category is ActionCategory.UNKNOWN or exceeds_materiality(materiality_inr, cap_inr):
        return "reject"
    return "approve"
