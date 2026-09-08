from aura.core.domain.enums import ActionCategory
from aura.core.ports.toolbox import ToolSpec
from aura.mcp.guard import classify_tools, is_gated


def test_known_tools_get_their_category():
    specs = [ToolSpec(name="get_deal_status", description="", schema={}),
             ToolSpec(name="send_email", description="", schema={})]
    mapping = classify_tools(specs)
    assert mapping["get_deal_status"] is ActionCategory.INTERNAL_READ
    assert mapping["send_email"] is ActionCategory.OUTBOUND


def test_unmapped_tool_is_gated():
    """A new MCP server cannot silently create an ungated path outward."""
    specs = [ToolSpec(name="wire_transfer_v2", description="", schema={})]
    assert classify_tools(specs)["wire_transfer_v2"] is ActionCategory.UNKNOWN
    assert is_gated("wire_transfer_v2") is True


def test_internal_read_is_not_gated():
    assert is_gated("get_deal_status") is False
