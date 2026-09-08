import pytest

from aura.core.domain.enums import ActionCategory
from aura.core.policy.gate_policy import classify, requires_approval


@pytest.mark.parametrize("tool,expected", [
    ("send_email", ActionCategory.OUTBOUND),
    ("create_invoice", ActionCategory.MONEY),
    ("draft_nda", ActionCategory.LEGAL),
    ("get_deal_status", ActionCategory.INTERNAL_READ),
    ("update_task_status", ActionCategory.INTERNAL_WRITE),
])
def test_known_tools_classify(tool, expected):
    assert classify(tool) is expected


def test_unknown_tool_is_unknown():
    assert classify("some_new_mcp_tool") is ActionCategory.UNKNOWN


@pytest.mark.parametrize("category", [
    ActionCategory.MONEY, ActionCategory.LEGAL,
    ActionCategory.OUTBOUND, ActionCategory.UNKNOWN,
])
def test_gated_categories_require_approval(category):
    assert requires_approval(category) is True


@pytest.mark.parametrize("category", [
    ActionCategory.INTERNAL_READ, ActionCategory.INTERNAL_WRITE,
])
def test_internal_categories_do_not_require_approval(category):
    assert requires_approval(category) is False


def test_unknown_tool_is_gated_end_to_end():
    """Default-deny: adding an MCP server cannot silently create an ungated path."""
    assert requires_approval(classify("brand_new_tool")) is True
