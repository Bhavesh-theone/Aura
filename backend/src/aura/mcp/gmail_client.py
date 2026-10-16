"""The Gmail port the Gmail MCP server calls, with the real adapter (google-api-python-client)
and a fake one for tests. Only aura.mcp.servers.gmail_server uses this module.

The fake is chosen only when AURA_GMAIL_FAKE=1 AND AURA_TEST_MODE=1 are both set, so a stray
AURA_GMAIL_FAKE in a real environment cannot silently swallow approved emails."""
import base64
import itertools
import json
import os
from email.message import EmailMessage
from typing import Protocol, runtime_checkable

from aura.core.policy.email_policy import normalise_email


@runtime_checkable
class GmailClient(Protocol):
    def create_draft(self, to: str, subject: str, body: str) -> dict:
        """{'id': draft id, 'message_id', 'thread_id'}"""
        ...

    def send(self, to: str, subject: str, body: str) -> dict:
        """{'id': message id, 'thread_id'}"""
        ...


def build_message(sender: str | None, to: str, subject: str, body: str) -> str:
    """RFC 2822 message, base64url-encoded for the Gmail API."""
    msg = EmailMessage()
    msg["To"] = normalise_email(to)
    if sender:
        msg["From"] = sender
    # Header values never carry line breaks (no header injection from a model's subject).
    msg["Subject"] = " ".join((subject or "").split())[:300]
    msg.set_content(body or "")
    return base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")


class GoogleGmailClient:
    """users.drafts.create / users.messages.send as the connected account."""

    def _service(self):
        from googleapiclient.discovery import build

        from aura.mcp.gmail_auth import load_credentials
        creds, account = load_credentials()
        return build("gmail", "v1", credentials=creds, cache_discovery=False), account

    def create_draft(self, to: str, subject: str, body: str) -> dict:
        service, account = self._service()
        raw = build_message(account, to, subject, body)
        draft = service.users().drafts().create(
            userId="me", body={"message": {"raw": raw}}).execute()
        message = draft.get("message") or {}
        return {"id": draft.get("id"), "message_id": message.get("id"),
                "thread_id": message.get("threadId")}

    def send(self, to: str, subject: str, body: str) -> dict:
        service, account = self._service()
        raw = build_message(account, to, subject, body)
        sent = service.users().messages().send(userId="me", body={"raw": raw}).execute()
        return {"id": sent.get("id"), "thread_id": sent.get("threadId")}


class FakeGmailClient:
    """Records calls (and appends them to AURA_GMAIL_FAKE_LOG when set). Never networks."""
    _ids = itertools.count(1)

    def __init__(self):
        self.calls: list[dict] = []

    def _record(self, kind: str, to: str, subject: str, body: str) -> int:
        n = next(self._ids)
        build_message("fake@example.com", to, subject, body)  # same validation as the real one
        call = {"kind": kind, "to": to, "subject": subject, "body": body, "n": n}
        self.calls.append(call)
        log = os.environ.get("AURA_GMAIL_FAKE_LOG")
        if log:
            with open(log, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(call) + "\n")
        return n

    def create_draft(self, to: str, subject: str, body: str) -> dict:
        n = self._record("draft", to, subject, body)
        return {"id": f"fake-draft-{n}", "message_id": f"fake-msg-{n}",
                "thread_id": f"fake-thread-{n}"}

    def send(self, to: str, subject: str, body: str) -> dict:
        n = self._record("send", to, subject, body)
        return {"id": f"fake-msg-{n}", "thread_id": f"fake-thread-{n}"}


def fake_enabled() -> bool:
    return os.environ.get("AURA_GMAIL_FAKE") == "1" and os.environ.get("AURA_TEST_MODE") == "1"


def default_client() -> GmailClient:
    return FakeGmailClient() if fake_enabled() else GoogleGmailClient()
