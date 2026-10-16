"""First-party MCP server. Run standalone over stdio, or import the plain functions.

Tool names must match keys in aura.core.policy.gate_policy.TOOL_CATEGORIES —
an unmapped name is treated as gated by default-deny.

The server enforces gate_policy itself, so a client that talks to it directly (not through
the crew's GatedTool wrapper) gets the same rule: a gated tool (send_email, anything over the
materiality cap) never runs its body here either and answers with a structured
"requires human approval" result.

Every deal read and write goes through repositories built for the acting user
(aura.mcp.identity), so deal walls apply here exactly as they do in the API: a deal behind a
wall the user is not on is reported as not found.
"""
import functools
import inspect
import json

from mcp.server.fastmcp import FastMCP

from aura.core.domain.errors import NotFound, RuleViolation
from aura.core.policy.gate_policy import classify, requires_approval
from aura.core.services.notes import add_note
from aura.data.engine import SessionLocal
from aura.data.repositories.sql import SqlAuditRepository
from aura.data.repositories.sql_deals import SqlDealRepository
from aura.data.repositories.sql_harness import SqlNoteRepository
from aura.data.uow import SqlUnitOfWork
from aura.mcp.identity import acting_username

mcp = FastMCP("yuki-deals")


def _materiality(arguments: dict) -> int | None:
    value = arguments.get("amount_inr")
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) \
        else None


def approval_required(tool: str, arguments: dict) -> str:
    category = classify(tool)
    return json.dumps({
        "status": "requires_human_approval", "executed": False, "tool": tool,
        "category": category.value,
        "message": f"'{tool}' needs human approval, so this server did not run it. Ask a "
                   "person to approve it through Aura's Decisions inbox."})


def gated(fn):
    """Check gate_policy before the tool body runs; a gated call never reaches the body."""
    signature = inspect.signature(fn)

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        from aura.config import get_settings
        bound = signature.bind_partial(*args, **kwargs)
        if requires_approval(classify(fn.__name__), _materiality(bound.arguments),
                             get_settings().materiality_cap_inr):
            return approval_required(fn.__name__, dict(bound.arguments))
        return fn(*args, **kwargs)
    return wrapper


@mcp.tool()
@gated
def get_deal_status(deal_id: str) -> str:
    """Look up the current stage of a deal by its ID (e.g. D-001)."""
    with SessionLocal() as s:
        deal = SqlDealRepository(s, acting_username()).get_by_external_id(deal_id)
    if deal is None:
        return f"No deal found with ID {deal_id}"
    return (f"{deal_id} ({deal.name}): {deal.stage.value}, {deal.transaction_class.value}, "
            f"owned by {deal.owner}")


@mcp.tool()
@gated
def list_deals() -> str:
    """List all deals with their current stage."""
    with SessionLocal() as s:
        deals = SqlDealRepository(s, acting_username()).list_all()
    return "\n".join(f"{d.external_id} - {d.name}: {d.stage.value}" for d in deals)


@mcp.tool()
@gated
def add_internal_note(deal_id: str, note: str) -> str:
    """Attach an internal note to a deal. Not visible outside the company."""
    user = acting_username()
    with SessionLocal() as s:
        try:
            with SqlUnitOfWork(s).transaction():
                saved = add_note(deal_id, note, user, "mcp_tool",
                                 SqlDealRepository(s, user), SqlNoteRepository(s, user),
                                 SqlAuditRepository(s, user))
        except NotFound:
            return f"No deal found with ID {deal_id}"
        except RuleViolation as exc:
            return f"Note not added: {exc}"
    return f"Note {saved.id} added to {deal_id}: {saved.body}"


@mcp.tool()
@gated
def send_email(to: str, subject: str, body: str) -> str:
    """Send an outbound email. GATED - requires human approval before it is sent."""
    # Unreachable while gate_policy gates outbound actions (see `gated`).
    return f"Email queued to {to} with subject '{subject}'"


if __name__ == "__main__":
    mcp.run(transport="stdio")
