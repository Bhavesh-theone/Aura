"""First-party MCP server. Run standalone over stdio, or import the plain functions.

Tool names must match keys in aura.core.policy.gate_policy.TOOL_CATEGORIES —
an unmapped name is treated as gated by default-deny.
"""
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("yuki-deals")

_DEALS = {
    "D-001": {"name": "Sunrise Infra", "stage": "NDA signed, awaiting mandate",
              "owner": "bhavesh"},
    "D-002": {"name": "Ravi Menon Ventures", "stage": "Sourced, no contact yet",
              "owner": "bhavesh"},
    "D-003": {"name": "Kaveri Textiles", "stage": "Closed - won", "owner": "bhavesh"},
}


@mcp.tool()
def get_deal_status(deal_id: str) -> str:
    """Look up the current stage of a deal by its ID (e.g. D-001)."""
    deal = _DEALS.get(deal_id)
    if deal is None:
        return f"No deal found with ID {deal_id}"
    return f"{deal_id} ({deal['name']}): {deal['stage']}, owned by {deal['owner']}"


@mcp.tool()
def list_deals() -> str:
    """List all deals with their current stage."""
    return "\n".join(f"{k} - {v['name']}: {v['stage']}" for k, v in _DEALS.items())


@mcp.tool()
def add_internal_note(deal_id: str, note: str) -> str:
    """Attach an internal note to a deal. Not visible outside the company."""
    return f"Note added to {deal_id}: {note}"


@mcp.tool()
def send_email(to: str, subject: str, body: str) -> str:
    """Send an outbound email. GATED - requires human approval before it is sent."""
    return f"Email queued to {to} with subject '{subject}'"


if __name__ == "__main__":
    mcp.run(transport="stdio")
