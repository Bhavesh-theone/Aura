"""Outbound email rules that are pure data: what an approval must look like to cover an
email, and what the approve option of a draft_email handoff says it will do in each mode."""
from aura.core.domain.enums import HandoffStatus
from aura.core.domain.handoff import Handoff
from aura.core.domain.outbound import OutboundMessage, OutboundMode, OutboundStatus

DRAFT_TASK = "draft_email"
APPROVE = "approve"

APPROVE_LABELS = {
    OutboundMode.OFF: "Approve (outbound off — nothing will be sent)",
    OutboundMode.GMAIL_DRAFT: "Approve → create Gmail draft",
    OutboundMode.GMAIL_SEND: "Approve → send via Gmail",
}
APPROVE_CONSEQUENCES = {
    OutboundMode.OFF: "The job completes and the draft stays in Aura. Outbound email is off "
                      "(AURA_OUTBOUND_MODE=off), so nothing is sent or drafted in Gmail.",
    OutboundMode.GMAIL_DRAFT: "After pre-send checks the email is saved as a DRAFT in the "
                              "connected Gmail account; a person sends it from Gmail.",
    OutboundMode.GMAIL_SEND: "After pre-send checks the email is SENT from the connected Gmail "
                             "account. This cannot be undone.",
}



def is_approved_draft(handoff: Handoff | None) -> bool:
    """A resolved draft_email handoff whose directive decided 'approve'."""
    return (handoff is not None and handoff.status is HandoffStatus.RESOLVED
            and handoff.task_type == DRAFT_TASK
            and (handoff.directive or {}).get("decision") == APPROVE)


def approved_package(handoff: Handoff) -> dict:
    """The proposed action's arguments as the approver saw them."""
    return dict(((handoff.context_package or {}).get("proposed_action") or {})
                .get("arguments") or {})


def approval_refusal(handoff: Handoff | None, to: str,
                     existing: OutboundMessage | None) -> str | None:
    """Why an approval does not cover sending `to` (None when it does). Shared by the worker's
    checks and the Gmail MCP server's own re-check."""
    if handoff is None:
        return "approval not found"
    if handoff.status is not HandoffStatus.RESOLVED:
        return "approval is not resolved"
    if handoff.task_type != DRAFT_TASK:
        return "approval is not for a draft_email"
    if (handoff.directive or {}).get("decision") != APPROVE:
        return "approval decision was not 'approve'"
    approved_to = (approved_package(handoff).get("to_email") or "").lower()
    if not approved_to or approved_to != (to or "").strip().lower():
        return "recipient does not match the approved package"
    if existing is not None and existing.status in (OutboundStatus.DRAFTED,
                                                    OutboundStatus.SENT):
        return "this approval was already used"
    return None
