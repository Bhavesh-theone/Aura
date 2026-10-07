"""Outbound email: the one place an approved email leaves Aura, and the one place an outbound
execution is recorded.

Agents never send. A draft_email job stops at a handoff; only when a person resolves that
handoff with 'approve' does the job resume, and only then does the worker (never the HTTP
request, never the crew) run `OutboundService.execute_after_approval`. It checks, in order and
deterministically:

  outbound mode is not 'off'; the approved recipient is still the party's verified primary
  email; the address (or its domain) is not suppressed; the approver is still on the deal's
  wall; Gmail is connected; today's cap (outbound_daily_limit) is not reached.

Any failed check writes an outbound_message row with status 'blocked' and an
'outbound_blocked' audit row, and the job completes with the block in its result. Otherwise the
row is queued (and committed) BEFORE the mailer is called, so a retry or a resumed segment finds
it and never sends twice (one outbound_message per handoff, a unique key). The mailer goes
through the Gmail MCP server, which re-checks the approval itself before it touches Gmail.

Every successful execution calls `record_outbound_executed` (audit 'outbound_executed', the
SM5 metric, now "approved executions"). `outbound_metrics` also counts executions WITHOUT an
approval, which must stay 0.
"""
from dataclasses import dataclass, replace

from aura.core.clock import utcnow
from aura.core.domain.audit import AuditEntry
from aura.core.domain.handoff import Handoff
from aura.core.domain.job import Job
from aura.core.domain.outbound import (BlockReason, MailResult, OutboundMessage, OutboundMode,
                                       OutboundStatus)
from aura.core.domain.segment import ProposedAction, Segment
from aura.core.policy.email_policy import domain_of
from aura.core.policy.outbound_policy import (APPROVE_LABELS, DRAFT_TASK, approved_package,
                                              is_approved_draft)
from aura.core.ports.events import EventPublisher
from aura.core.ports.mailer import OutboundMailer
from aura.core.ports.repositories import (AuditRepository, ContactRepository,
                                          HandoffRepository, OutboundRepository,
                                          SuppressionRepository, WallRepository)
from aura.core.ports.uow import UnitOfWork
from aura.core.services.contacts import primary_contact, primary_verified_email
from aura.core.services.segment_reliability import start_of_utc_day
from aura.core.tracing import current_trace, tracer

GMAIL_DRAFTS_URL = "https://mail.google.com/mail/u/0/#drafts"


def record_outbound_executed(tool: str, arguments: dict, actor: str, deal_id: int | None,
                             job_id: int | None, audit: AuditRepository,
                             **details) -> AuditEntry:
    """The audit row of an outbound action that actually happened. Every executor calls this
    after it acts, so the metric sees it."""
    return audit.append(AuditEntry(
        id=None, job_id=job_id, deal_id=deal_id, actor=actor, action="outbound_executed",
        created_at=utcnow(),
        payload={"tool": tool, "argument_names": sorted(arguments), **details}))


@dataclass
class OutboundSettings:
    mode: OutboundMode = OutboundMode.OFF
    daily_limit: int = 50


def _summary(message: OutboundMessage, replayed: bool = False) -> dict:
    out = {"outbound_id": message.id, "status": message.status.value,
           "mode": message.mode.value, "to": message.to_email, "handoff_id": message.handoff_id,
           "gmail_id": message.gmail_id, "gmail_thread_id": message.gmail_thread_id,
           "reason": message.error}
    if message.status is OutboundStatus.DRAFTED:
        out["link"] = GMAIL_DRAFTS_URL
    if replayed:
        out["replayed"] = True
    return out


class OutboundService:
    """Built by the worker for one segment. `uow` lets it commit the queued row before the
    mailer runs (no database lock is held across the Gmail call)."""

    def __init__(self, *, settings: OutboundSettings, contacts: ContactRepository,
                 suppressions: SuppressionRepository, messages: OutboundRepository,
                 handoffs: HandoffRepository, walls: WallRepository, audit: AuditRepository,
                 events: EventPublisher, mailer: OutboundMailer, uow: UnitOfWork):
        self.settings, self.contacts, self.suppressions = settings, contacts, suppressions
        self.messages, self.handoffs, self.walls = messages, handoffs, walls
        self.audit, self.events, self.mailer, self.uow = audit, events, mailer, uow

    # --- the draft's handoff -------------------------------------------------------------

    def describe_draft(self, action: ProposedAction) -> ProposedAction:
        """Put the resolved recipient and the outbound mode into a draft_email action, so the
        person approving sees exactly where the email would go and what approving does."""
        if action.tool != DRAFT_TASK:
            return action
        party_id = action.arguments.get("party_id")
        contact = primary_contact(party_id if isinstance(party_id, int) else None,
                                  self.contacts)
        mode = self.settings.mode
        return replace(action, arguments={
            **action.arguments,
            "to_email": contact.email if contact else None,
            "to_email_verified": bool(contact and contact.verified_at is not None),
            "outbound_mode": mode.value,
            "approve_label": APPROVE_LABELS[mode]})

    # --- after approval ------------------------------------------------------------------

    @staticmethod
    def applies(segment: Segment) -> bool:
        """A resumed draft_email segment: its draft went to a person and the job came back."""
        ctx = segment.context_in or {}
        return segment.seq > 1 and ctx.get("capability") == DRAFT_TASK \
            and bool(ctx.get("proposal_made"))

    def _approval(self, job: Job) -> Handoff | None:
        """This job's own draft_email handoff. A job resumed by an earlier directive
        (do_not_revisit) has none: an approval of another email never covers this one."""
        for h in self.handoffs.list_all(resolved=True):
            if h.job_id == job.id and h.task_type == DRAFT_TASK:
                return h
        return None

    def _check(self, handoff: Handoff, job: Job, to: str | None,
               party_id: int | None) -> BlockReason | None:
        if self.settings.mode is OutboundMode.OFF:
            return BlockReason.OUTBOUND_OFF
        verified = primary_verified_email(party_id, self.contacts)
        if not to or verified is None:
            return BlockReason.NO_VERIFIED_EMAIL
        if verified != to.lower():
            return BlockReason.RECIPIENT_CHANGED
        if self.suppressions.matches(to) is not None:
            return BlockReason.SUPPRESSED
        approver = handoff.resolved_by or ""
        if job.deal_id is None or approver not in {m.username for m in
                                                   self.walls.members(job.deal_id)}:
            return BlockReason.APPROVER_NOT_ON_WALL
        status = self.mailer.status()
        if status.needs_reconnect:
            return BlockReason.GMAIL_RECONNECT_NEEDED
        if not status.connected:
            return BlockReason.GMAIL_NOT_CONNECTED
        if self.messages.count_since(start_of_utc_day(utcnow())) >= self.settings.daily_limit:
            return BlockReason.DAILY_LIMIT_REACHED
        return None

    def _blocked_audit(self, job: Job, reason: str, handoff_id: int | None,
                       to: str | None, **extra) -> None:
        self.audit.append(AuditEntry(
            id=None, job_id=job.id, deal_id=job.deal_id, actor="system",
            action="outbound_blocked", created_at=utcnow(),
            payload={"reason": reason, "handoff_id": handoff_id, "to": to or None,
                     "mode": self.settings.mode.value, **extra}))

    def execute_after_approval(self, job: Job) -> dict:
        """Run the approved email through the checks and the mailer. Returns what happened,
        for the job's result. Idempotent per handoff."""
        with tracer.span("outbound.check", {"aura.job_id": job.id,
                                            "aura.outbound_mode": self.settings.mode.value},
                         deal_id=job.deal_id) as span:
            handoff = self._approval(job)
            if not is_approved_draft(handoff):
                reason = BlockReason.NO_EXPLICIT_APPROVAL.value
                span.set("aura.blocked_reason", reason)
                self._blocked_audit(job, reason, handoff.id if handoff else None, None)
                self.uow.commit()
                return {"status": "blocked", "reason": reason, "handoff_id": None}
            span.set("aura.handoff_id", handoff.id)
            existing = self.messages.get_for_handoff(handoff.id)
            if existing is not None:
                span.set("aura.replayed", True)
                return _summary(existing, replayed=True)

            args = approved_package(handoff)
            to = (args.get("to_email") or "").strip().lower() or None
            party_id = args.get("party_id") if isinstance(args.get("party_id"), int) else None
            subject = str(args.get("subject") or "")
            body = str(args.get("body") or "")
            span.set("aura.recipient_domain", domain_of(to or "") or None)
            reason = self._check(handoff, job, to, party_id)
            mode = self.settings.mode
            message = OutboundMessage(
                id=None, handoff_id=handoff.id, job_id=job.id, deal_id=job.deal_id,
                party_id=party_id, to_email=to or "", subject=subject[:500], mode=mode,
                status=OutboundStatus.BLOCKED if reason else OutboundStatus.QUEUED,
                created_at=utcnow(), error=reason.value if reason else None,
                completed_at=utcnow() if reason else None, trace_id=current_trace()[0])
            message = self.messages.add(message)
            if reason:
                span.set("aura.blocked_reason", reason.value)
                self._blocked_audit(job, reason.value, handoff.id, to,
                                    outbound_id=message.id)
                self.events.publish("outbound_blocked", {"job_id": job.id,
                                                         "deal_id": job.deal_id,
                                                         "handoff_id": handoff.id})
                self.uow.commit()
                return _summary(message)
            self.uow.commit()  # queued and durable before anything leaves

        with tracer.span("outbound.gmail", {"aura.outbound_mode": mode.value,
                                            "aura.recipient_domain": domain_of(to or ""),
                                            "aura.handoff_id": handoff.id},
                         deal_id=job.deal_id) as span:
            try:
                if mode is OutboundMode.GMAIL_SEND:
                    result = self.mailer.send(handoff.id, to, subject, body)
                else:
                    result = self.mailer.create_draft(handoff.id, to, subject, body)
            except Exception as exc:  # the mailer is a subprocess and a network: anything
                result = MailResult(status="failed",
                                    reason=f"{type(exc).__name__}: {exc}"[:500])
            span.set("aura.result", result.status)
        return self._finish(job, handoff, message, result)

    def _finish(self, job: Job, handoff: Handoff, message: OutboundMessage,
                result: MailResult) -> dict:
        now = utcnow()
        message.completed_at = now
        if result.status in ("drafted", "sent"):
            message.status = OutboundStatus(result.status)
            message.gmail_id, message.gmail_thread_id = result.gmail_id, result.gmail_thread_id
            self.messages.update(message)
            kind = "send" if message.status is OutboundStatus.SENT else "draft"
            record_outbound_executed(
                "send_gmail" if kind == "send" else "create_gmail_draft",
                {"to": 1, "subject": 1, "body": 1}, "system", job.deal_id, job.id, self.audit,
                kind=kind, gmail_id=result.gmail_id, to=message.to_email,
                handoff_id=handoff.id, outbound_id=message.id,
                approved_by=handoff.resolved_by)
            self.events.publish("outbound_executed", {"job_id": job.id, "deal_id": job.deal_id,
                                                      "handoff_id": handoff.id})
        elif result.status == "refused":
            message.status = OutboundStatus.BLOCKED
            message.error = BlockReason.REFUSED_BY_SERVER.value
            self.messages.update(message)
            self._blocked_audit(job, BlockReason.REFUSED_BY_SERVER.value, handoff.id,
                                message.to_email, outbound_id=message.id,
                                detail=(result.reason or "")[:300])
        else:
            message.status = OutboundStatus.FAILED
            message.error = (result.reason or "unknown error")[:500]
            self.messages.update(message)
            self.audit.append(AuditEntry(
                id=None, job_id=job.id, deal_id=job.deal_id, actor="system",
                action="outbound_failed", created_at=now,
                payload={"handoff_id": handoff.id, "outbound_id": message.id,
                         "error": message.error}))
        self.uow.commit()
        return _summary(message)


@dataclass
class OutboundMetrics:
    mode: str
    drafted: int
    sent: int
    blocked: int
    failed: int
    blocked_by_reason: dict
    # Executions with no approved draft_email handoff behind them. Structurally impossible:
    # must be 0.
    outbound_without_approval: int


def outbound_metrics(messages: OutboundRepository, handoffs: HandoffRepository,
                     audit: AuditRepository, mode: OutboundMode) -> OutboundMetrics:
    rows = messages.list_all(limit=1_000_000)
    by_status = {s: [m for m in rows if m.status is s] for s in OutboundStatus}
    executed = by_status[OutboundStatus.DRAFTED] + by_status[OutboundStatus.SENT]
    unapproved = sum(1 for m in executed if not is_approved_draft(handoffs.get(m.handoff_id)))
    # An 'outbound_executed' audit row with no outbound_message behind it was not executed
    # through this path at all.
    stray = max(0, audit.count_by_action("outbound_executed") - len(executed))
    reasons: dict[str, int] = {}
    for m in by_status[OutboundStatus.BLOCKED]:
        reasons[m.error or "unknown"] = reasons.get(m.error or "unknown", 0) + 1
    return OutboundMetrics(mode=mode.value, drafted=len(by_status[OutboundStatus.DRAFTED]),
                           sent=len(by_status[OutboundStatus.SENT]),
                           blocked=len(by_status[OutboundStatus.BLOCKED]),
                           failed=len(by_status[OutboundStatus.FAILED]),
                           blocked_by_reason=reasons,
                           outbound_without_approval=unapproved + stray)
