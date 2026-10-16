from typing import Protocol, runtime_checkable

from aura.core.domain.outbound import MailerStatus, MailResult


@runtime_checkable
class OutboundMailer(Protocol):
    """Puts an approved email into Gmail. The adapter (aura.agents.gmail_mailer) talks to the
    Gmail MCP server, which checks the approval again before it calls Gmail. Agents never get
    this port: only the worker's outbound step holds one."""

    def status(self) -> MailerStatus:
        """The connection as stored locally (no network call, never a token)."""
        ...

    def create_draft(self, approval_id: int, to: str, subject: str, body: str) -> MailResult:
        ...

    def send(self, approval_id: int, to: str, subject: str, body: str) -> MailResult: ...
