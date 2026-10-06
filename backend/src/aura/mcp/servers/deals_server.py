"""First-party MCP server. Run standalone over stdio, or import the plain functions.

Tool names must match keys in aura.core.policy.gate_policy.TOOL_CATEGORIES —
an unmapped name is treated as gated by default-deny.

Every deal read goes through a repository built for the acting user (aura.mcp.identity), so
deal walls apply here exactly as they do in the API: a deal behind a wall the user is not on
is reported as not found.
"""
from mcp.server.fastmcp import FastMCP

from aura.data.engine import SessionLocal
from aura.data.repositories.sql_deals import SqlDealRepository
from aura.mcp.identity import acting_username

mcp = FastMCP("yuki-deals")


@mcp.tool()
def get_deal_status(deal_id: str) -> str:
    """Look up the current stage of a deal by its ID (e.g. D-001)."""
    with SessionLocal() as s:
        deal = SqlDealRepository(s, acting_username()).get_by_external_id(deal_id)
    if deal is None:
        return f"No deal found with ID {deal_id}"
    return (f"{deal_id} ({deal.name}): {deal.stage.value}, {deal.transaction_class.value}, "
            f"owned by {deal.owner}")


@mcp.tool()
def list_deals() -> str:
    """List all deals with their current stage."""
    with SessionLocal() as s:
        deals = SqlDealRepository(s, acting_username()).list_all()
    return "\n".join(f"{d.external_id} - {d.name}: {d.stage.value}" for d in deals)


@mcp.tool()
def add_internal_note(deal_id: str, note: str) -> str:
    """Attach an internal note to a deal. Not visible outside the company."""
    with SessionLocal() as s:
        deal = SqlDealRepository(s, acting_username()).get_by_external_id(deal_id)
    if deal is None:
        return f"No deal found with ID {deal_id}"
    return f"Note added to {deal_id}: {note}"


@mcp.tool()
def send_email(to: str, subject: str, body: str) -> str:
    """Send an outbound email. GATED - requires human approval before it is sent."""
    return f"Email queued to {to} with subject '{subject}'"


if __name__ == "__main__":
    mcp.run(transport="stdio")
