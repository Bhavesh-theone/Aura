"""First-party Gmail MCP server (stdio). Exactly two tools, no inbox reading:

    create_gmail_draft(approval_id, to, subject, body)
    send_gmail(approval_id, to, subject, body)

The crew never gets these tools (gate_policy maps both to OUTBOUND, and they are not among
the crew's deal tools). Only the worker's outbound step reaches this server, through
aura.agents.gmail_mailer, after a person approved the email.

The server trusts nobody, including that caller: each tool re-reads, as SYSTEM, the approval
it is given and refuses ({"status": "refused", "reason": ...}, Gmail never called) unless it
is a RESOLVED draft_email handoff decided 'approve', its approved recipient is `to`, and no
outbound_message for it is already drafted or sent. send_gmail also refuses unless
AURA_OUTBOUND_MODE is 'gmail_send'; create_gmail_draft refuses while it is 'off'.

The server writes nothing to the database: the worker records the outcome.
"""
from aura.core.domain.errors import RuleViolation
from aura.core.policy.email_policy import normalise_email
from aura.core.policy.outbound_policy import approval_refusal
from aura.data.engine import SessionLocal
from aura.data.repositories.sql import SqlHandoffRepository
from aura.data.repositories.sql_outbound import SqlOutboundRepository
from aura.data.walls import SYSTEM
from aura.mcp import gmail_client
from aura.mcp.gmail_auth import GmailNotConnected, GmailReconnectNeeded

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("aura-gmail")

# The Gmail port; tests swap it (or set AURA_GMAIL_FAKE=1 with AURA_TEST_MODE=1).
client_factory = gmail_client.default_client


def _mode() -> str:
    from aura.config import get_settings
    return get_settings().outbound_mode


def _refused(reason: str) -> dict:
    return {"status": "refused", "reason": reason}


def verify(approval_id, to: str) -> str | None:
    """Why this call must not reach Gmail, or None."""
    if isinstance(approval_id, bool) or not isinstance(approval_id, int):
        return "approval_id must be an integer"
    try:
        normalise_email(to)
    except RuleViolation as exc:
        return str(exc)
    with SessionLocal() as s:
        handoff = SqlHandoffRepository(s, SYSTEM).get(approval_id)
        existing = SqlOutboundRepository(s, SYSTEM).get_for_handoff(approval_id)
    return approval_refusal(handoff, to, existing)


def _call(kind: str, approval_id, to: str, subject: str, body: str) -> dict:
    mode = _mode()
    if mode == "off":
        return _refused("outbound mode is off")
    if kind == "send" and mode != "gmail_send":
        return _refused(f"sending is not enabled (outbound mode is {mode})")
    try:
        reason = verify(approval_id, to)
    except Exception as exc:  # cannot check the approval: refuse, say why without detail
        return _refused(f"approval could not be checked ({type(exc).__name__})")
    if reason is not None:
        return _refused(reason)
    client = client_factory()
    try:
        if kind == "send":
            result = client.send(to, subject, body)
            return {"status": "sent", "gmail_id": result.get("id"),
                    "gmail_thread_id": result.get("thread_id")}
        result = client.create_draft(to, subject, body)
        return {"status": "drafted", "gmail_id": result.get("id"),
                "gmail_thread_id": result.get("thread_id")}
    except GmailReconnectNeeded:
        return {"status": "failed", "reason": "gmail_reconnect_needed"}
    except GmailNotConnected:
        return {"status": "failed", "reason": "gmail_not_connected"}
    except Exception as exc:  # never echo a response body: it could carry PII or tokens
        return {"status": "failed", "reason": f"gmail error: {type(exc).__name__}"}


@mcp.tool()
def create_gmail_draft(approval_id: int, to: str, subject: str, body: str) -> dict:
    """Save an APPROVED email as a draft in the connected Gmail account. Refused unless
    approval_id is an approved draft_email handoff for exactly this recipient."""
    return _call("draft", approval_id, to, subject, body)


@mcp.tool()
def send_gmail(approval_id: int, to: str, subject: str, body: str) -> dict:
    """Send an APPROVED email from the connected Gmail account. Refused unless outbound mode
    is gmail_send and approval_id is an approved draft_email handoff for this recipient."""
    return _call("send", approval_id, to, subject, body)


if __name__ == "__main__":
    mcp.run(transport="stdio")
