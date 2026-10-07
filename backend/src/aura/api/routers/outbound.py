"""Outbound email: the suppression list, the outbound log and the Gmail connection status.

The outbound MODE is deliberately not settable here: it lives in backend/.env
(AURA_OUTBOUND_MODE), so turning sending on needs access to the server, not a click."""
from fastapi import APIRouter, Depends, Query, status

from aura.api.deps import (current_user, get_audit, get_mailer_status, get_outbound,
                           get_suppressions)
from aura.api.schemas.outbound import (CreateSuppressionRequest, GmailIntegrationOut,
                                       OutboundOut, SuppressionOut)
from aura.config import get_settings
from aura.core.clock import utcnow
from aura.core.domain.user import User
from aura.core.policy.rbac_policy import Capability, require
from aura.core.services.contacts import (add_suppression, list_suppressions,
                                         remove_suppression)
from aura.core.services.segment_reliability import start_of_utc_day
from aura.mcp.gmail_auth import CONNECT_COMMAND

router = APIRouter(tags=["outbound"])


def _suppression_out(e) -> SuppressionOut:
    return SuppressionOut(id=e.id, kind=e.kind.value, value=e.value, reason=e.reason,
                          created_by=e.created_by, created_at=e.created_at)


@router.get("/api/suppression", response_model=list[SuppressionOut])
def list_suppression(user: User = Depends(current_user), entries=Depends(get_suppressions)):
    return [_suppression_out(e) for e in list_suppressions(user.role, entries)]


@router.post("/api/suppression", response_model=SuppressionOut,
             status_code=status.HTTP_201_CREATED)
def create_suppression(body: CreateSuppressionRequest, user: User = Depends(current_user),
                       entries=Depends(get_suppressions), audit=Depends(get_audit)):
    return _suppression_out(add_suppression(body.kind, body.value, body.reason, user.username,
                                            user.role, entries, audit))


@router.delete("/api/suppression/{suppression_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_suppression(suppression_id: int, user: User = Depends(current_user),
                       entries=Depends(get_suppressions), audit=Depends(get_audit)):
    remove_suppression(suppression_id, user.username, user.role, entries, audit)


@router.get("/api/outbound", response_model=list[OutboundOut])
def list_outbound(handoff_id: int | None = Query(None), user: User = Depends(current_user),
                  messages=Depends(get_outbound)):
    """Wall-filtered: only messages on deals the viewer is on the wall for."""
    return [OutboundOut(id=m.id, handoff_id=m.handoff_id, job_id=m.job_id, deal_id=m.deal_id,
                        party_id=m.party_id, to_email=m.to_email, subject=m.subject,
                        mode=m.mode.value, status=m.status.value, gmail_id=m.gmail_id,
                        gmail_thread_id=m.gmail_thread_id, error=m.error,
                        created_at=m.created_at, completed_at=m.completed_at,
                        trace_id=m.trace_id)
            for m in messages.list_all(handoff_id=handoff_id)]


@router.get("/api/integrations/gmail", response_model=GmailIntegrationOut)
def gmail_integration(user: User = Depends(current_user), messages=Depends(get_outbound),
                      mailer_status=Depends(get_mailer_status)):
    """Admin and dealmaker. Never returns a token."""
    require(user.role, Capability.VIEW_INTEGRATIONS, "view integrations")
    s = get_settings()
    return GmailIntegrationOut(
        mode=s.outbound_mode, connected=mailer_status.connected,
        account_email=mailer_status.account_email, scopes=list(mailer_status.scopes),
        expires_at=mailer_status.expires_at, needs_reconnect=mailer_status.needs_reconnect,
        storage=mailer_status.storage, daily_limit=s.outbound_daily_limit,
        sent_today=messages.count_since(start_of_utc_day(utcnow())),
        connect_command=CONNECT_COMMAND, detail=mailer_status.detail)
