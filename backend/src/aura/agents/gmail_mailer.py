"""OutboundMailer adapter: puts an approved email into Gmail through the Gmail MCP server,
spawned over stdio with the official `mcp` client (one short-lived server per email).

Held only by the worker's outbound step (aura.worker.runner); never handed to a crew."""
import asyncio
import json
import os
import sys

from aura.config import BACKEND_DIR
from aura.core.domain.outbound import MailerStatus, MailResult

SERVER_MODULE = "aura.mcp.servers.gmail_server"
DEFAULT_TIMEOUT_SECONDS = 120.0


def _parse(result) -> MailResult:
    data = getattr(result, "structuredContent", None)
    if isinstance(data, dict) and "status" not in data and isinstance(data.get("result"), dict):
        data = data["result"]
    if not isinstance(data, dict):
        text = next((c.text for c in getattr(result, "content", None) or []
                     if getattr(c, "type", "") == "text"), "")
        try:
            data = json.loads(text)
        except (TypeError, ValueError):
            data = {"status": "failed", "reason": (text or "no answer from the server")[:300]}
    if getattr(result, "isError", False):
        return MailResult(status="failed", reason=str(data.get("reason") or "tool error"))
    return MailResult(status=str(data.get("status") or "failed"),
                      gmail_id=data.get("gmail_id"), gmail_thread_id=data.get("gmail_thread_id"),
                      reason=data.get("reason"))


class McpGmailMailer:
    def __init__(self, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
                 env: dict | None = None):
        self.timeout = timeout_seconds
        self.env = env

    def status(self) -> MailerStatus:
        from aura.mcp.gmail_client import fake_enabled
        if fake_enabled():
            return MailerStatus(connected=True, account_email="fake@example.com",
                                scopes=("https://www.googleapis.com/auth/gmail.compose",),
                                storage="fake")
        from aura.mcp.gmail_auth import stored_status
        return stored_status()

    def create_draft(self, approval_id: int, to: str, subject: str, body: str) -> MailResult:
        return self._call("create_gmail_draft", approval_id, to, subject, body)

    def send(self, approval_id: int, to: str, subject: str, body: str) -> MailResult:
        return self._call("send_gmail", approval_id, to, subject, body)

    def _call(self, tool: str, approval_id: int, to: str, subject: str,
              body: str) -> MailResult:
        args = {"approval_id": approval_id, "to": to, "subject": subject, "body": body}
        # The worker thread has no event loop of its own: one per call.
        return asyncio.run(asyncio.wait_for(self._acall(tool, args), self.timeout))

    async def _acall(self, tool: str, args: dict) -> MailResult:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        # The full environment: the server must read the same database and settings.
        env = dict(os.environ if self.env is None else self.env)
        env.setdefault("PYTHONIOENCODING", "utf-8")
        params = StdioServerParameters(command=sys.executable, args=["-m", SERVER_MODULE],
                                       env=env, cwd=str(BACKEND_DIR))
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return _parse(await session.call_tool(tool, args))
