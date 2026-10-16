"""Gated Gmail outbound email (migration 0013). The real Gmail API is never called: every test
uses the fake Gmail client, in process or behind the real MCP stdio server."""
import json
import os
from contextlib import contextmanager

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from aura.agents.crewai.tools import ToolGate, build_deal_tools, deals_server_functions
from aura.agents.gmail_mailer import McpGmailMailer
from aura.api.deps import get_mailer_status
from aura.api.main import app
from aura.config import get_settings
from aura.core.domain.enums import ActionCategory
from aura.core.domain.outbound import MailerStatus, MailResult
from aura.core.policy.gate_policy import classify, requires_approval
from aura.data.models.tables import HandoffRow, TaskRow, UserRow
from aura.data.repositories.sql_deals import SqlWallRepository
from aura.data.walls import SYSTEM
from aura.mcp import gmail_auth
from aura.mcp.gmail_client import FakeGmailClient
from aura.mcp.servers import gmail_server
from aura.worker import runner
from tests.integration.pgtest import fresh_engine
from tests.integration.helpers import (DIRECTIVE, NullEvents, link, make_deal, party,
                                       run_worker, submit)

TO = "ravi@acme-capital.in"


class InProcessMailer:
    """The worker's mailer, minus the subprocess: calls the Gmail MCP server's tool functions
    directly (same checks), with the fake Gmail client behind them."""

    def __init__(self, connected=True, needs_reconnect=False):
        self.connected, self.needs_reconnect = connected, needs_reconnect

    def status(self):
        return MailerStatus(connected=self.connected, needs_reconnect=self.needs_reconnect,
                            account_email="desk@example.com")

    def create_draft(self, approval_id, to, subject, body):
        return MailResult(**gmail_server.create_gmail_draft(approval_id, to, subject, body))

    def send(self, approval_id, to, subject, body):
        return MailResult(**gmail_server.send_gmail(approval_id, to, subject, body))


@pytest.fixture()
def gmail(api, monkeypatch):
    """Draft mode, a fake Gmail client, and the MCP server reading the test's session."""
    fake = FakeGmailClient()
    monkeypatch.setattr(gmail_server, "client_factory", lambda: fake)

    @contextmanager
    def shared():
        yield api.session
    monkeypatch.setattr(gmail_server, "SessionLocal", shared)
    mailer = InProcessMailer()
    monkeypatch.setattr(runner, "mailer_factory", lambda: mailer)
    settings = get_settings()
    monkeypatch.setattr(settings, "outbound_mode", "gmail_draft")
    monkeypatch.setattr(settings, "outbound_daily_limit", 50)
    fake.mailer = mailer
    return fake


def _deal_with_party(api, email=TO, verify=True, ext="OB-1"):
    deal = make_deal(api, ext)
    p = party(api, "Acme Capital")
    link(api, deal, p["id"], "lender")
    if email:
        r = api.call("POST", f"/api/parties/{p['id']}/contacts", user="asha",
                     json={"name": "Ravi Menon", "email": email.upper(), "is_primary": True})
        assert r.status_code == 201, r.text
        assert r.json()["email"] == email and r.json()["verified_at"] is None
        if verify:
            v = api.call("POST", f"/api/parties/contacts/{r.json()['id']}/verify")
            assert v.status_code == 200 and v.json()["verified_by"] == "bhavesh"
    return deal, p["id"]


def _draft_handoff(api, deal, party_id):
    job = submit(api, {"capability": "draft_email", "party_id": party_id,
                       "brief": "Introduce the mandate."}, deal)
    run_worker(api)
    (h,) = api.call("GET", "/api/handoffs", params={"status": "open"}).json()
    return job, h


def _approve(api, h, decision="approve"):
    r = api.call("POST", f"/api/handoffs/{h['id']}/resolve",
                 json={**DIRECTIVE, "decision": decision})
    assert r.status_code == 200, r.text
    run_worker(api)


def _outbound(api, handoff_id=None):
    params = {"handoff_id": handoff_id} if handoff_id else None
    return api.call("GET", "/api/outbound", params=params).json()


def _audit(api, action):
    return [p for (p,) in api.session.execute(
        text("SELECT payload FROM audit_entries WHERE action = :a ORDER BY id"),
        {"a": action})]


# --- the agent can never reach Gmail ------------------------------------------------------------

def test_the_crew_is_never_given_the_gmail_tools_and_they_are_gated():
    for tool in ("create_gmail_draft", "send_gmail"):
        assert classify(tool) is ActionCategory.OUTBOUND and requires_approval(classify(tool))
        assert ToolGate("x").needs_approval(tool, {})
    assert not {"create_gmail_draft", "send_gmail"} & set(deals_server_functions())
    names = {t.name for t in build_deal_tools(ToolGate("x"), "bhavesh")}
    assert names and not {"create_gmail_draft", "send_gmail"} & names


# --- the draft_email flow ---------------------------------------------------------------------

def test_an_approved_draft_becomes_one_gmail_draft(api, gmail):
    deal, party_id = _deal_with_party(api)
    job, h = _draft_handoff(api, deal, party_id)
    package = h["context_package"]
    args = package["proposed_action"]["arguments"]
    assert args["to_email"] == TO and args["to_email_verified"] is True
    approve = package["decision_required"]["options"][0]
    assert approve["id"] == "approve" and approve["label"] == "Approve → create Gmail draft"
    assert {"type": "recipient", "email": TO, "verified": True, "mode": "gmail_draft",
            "action_label": "Approve → create Gmail draft"} in package["evidence"]
    assert gmail.calls == [] and _outbound(api) == []  # nothing before approval

    _approve(api, h)
    (msg,) = _outbound(api, h["id"])
    assert msg["status"] == "drafted" and msg["gmail_id"] == "fake-draft-1"
    assert msg["to_email"] == TO and msg["mode"] == "gmail_draft"
    assert [c["kind"] for c in gmail.calls] == ["draft"] and gmail.calls[0]["to"] == TO
    done = api.call("GET", f"/api/jobs/{job['id']}").json()
    assert done["status"] == "complete" and done["result"]["outbound"]["status"] == "drafted"
    assert done["result"]["outbound"]["link"].startswith("https://mail.google.com/")
    (executed,) = _audit(api, "outbound_executed")
    assert executed["kind"] == "draft" and executed["handoff_id"] == h["id"]
    assert executed["to"] == TO and executed["approved_by"] == "bhavesh"

    m = api.call("GET", "/api/metrics").json()
    assert m["success"]["outbound_executed"] == 1
    assert m["outbound"]["drafted"] == 1 and m["outbound"]["outbound_without_approval"] == 0
    spans = {n for (n,) in api.session.execute(text("SELECT name FROM trace_span"))}
    assert {"outbound.check", "outbound.gmail"} <= spans
    attrs = [a for (a,) in api.session.execute(text(
        "SELECT attributes FROM trace_span WHERE name LIKE 'outbound.%'"))]
    assert all("ravi@" not in str(a) for a in attrs)  # domain only, no address

    # A retried or resumed segment finds the row and sends nothing more.
    svc = runner.outbound_service(api.session, runner.SqlAuditRepository(api.session, SYSTEM),
                                  NullEvents(), runner.SqlUnitOfWork(api.session))
    job_obj = runner.SqlJobRepository(api.session, SYSTEM).get(job["id"])
    assert svc.execute_after_approval(job_obj)["replayed"] is True
    assert len(gmail.calls) == 1 and len(_outbound(api)) == 1
    # And the MCP server itself refuses to use the approval twice.
    again = gmail_server.create_gmail_draft(h["id"], TO, "s", "b")
    assert again == {"status": "refused", "reason": "this approval was already used"}


def test_send_mode_sends_and_says_so(api, gmail, monkeypatch):
    monkeypatch.setattr(get_settings(), "outbound_mode", "gmail_send")
    deal, party_id = _deal_with_party(api)
    _, h = _draft_handoff(api, deal, party_id)
    assert h["context_package"]["decision_required"]["options"][0]["label"] == \
        "Approve → send via Gmail"
    _approve(api, h)
    (msg,) = _outbound(api)
    assert msg["status"] == "sent" and [c["kind"] for c in gmail.calls] == ["send"]
    assert _audit(api, "outbound_executed")[0]["kind"] == "send"


def test_off_mode_sends_nothing_and_records_the_block(api, gmail, monkeypatch):
    monkeypatch.setattr(get_settings(), "outbound_mode", "off")
    deal, party_id = _deal_with_party(api)
    job, h = _draft_handoff(api, deal, party_id)
    assert h["context_package"]["decision_required"]["options"][0]["label"] == \
        "Approve (outbound off — nothing will be sent)"
    _approve(api, h)
    (msg,) = _outbound(api)
    assert msg["status"] == "blocked" and msg["error"] == "outbound_off"
    assert gmail.calls == [] and _audit(api, "outbound_executed") == []
    assert _audit(api, "outbound_blocked")[0]["reason"] == "outbound_off"
    done = api.call("GET", f"/api/jobs/{job['id']}").json()
    assert done["status"] == "complete" and done["result"]["outbound"]["reason"] == "outbound_off"


def test_a_rejected_draft_never_reaches_the_outbound_step(api, gmail):
    deal, party_id = _deal_with_party(api)
    _, h = _draft_handoff(api, deal, party_id)
    _approve(api, h, "reject")
    assert _outbound(api) == [] and gmail.calls == []


@pytest.mark.parametrize("case, reason", [
    ("unverified", "no_verified_email"), ("no_contact", "no_verified_email"),
    ("suppressed_domain", "suppressed"), ("suppressed_email", "suppressed"),
    ("cap", "daily_limit_reached"), ("not_connected", "gmail_not_connected"),
    ("reconnect", "gmail_reconnect_needed"), ("off_wall", "approver_not_on_wall"),
    ("recipient_changed", "recipient_changed"),
])
def test_pre_send_checks_block_and_are_audited(api, gmail, monkeypatch, case, reason):
    deal, party_id = _deal_with_party(api, email=None if case == "no_contact" else TO,
                                      verify=case != "unverified")
    _, h = _draft_handoff(api, deal, party_id)
    if case == "suppressed_domain":
        r = api.call("POST", "/api/suppression", user="priya",
                     json={"kind": "domain", "value": "@Acme-Capital.in", "reason": "opted out"})
        assert r.status_code == 201 and r.json()["value"] == "acme-capital.in"
    elif case == "suppressed_email":
        assert api.call("POST", "/api/suppression", json={
            "kind": "email", "value": TO, "reason": "asked us to stop"}).status_code == 201
    elif case == "cap":
        monkeypatch.setattr(get_settings(), "outbound_daily_limit", 0)
    elif case == "not_connected":
        gmail.mailer.connected = False
    elif case == "reconnect":
        gmail.mailer.needs_reconnect = True
    elif case == "recipient_changed":
        r = api.call("POST", f"/api/parties/{party_id}/contacts", json={
            "name": "New", "email": "other@acme-capital.in", "is_primary": True})
        api.call("POST", f"/api/parties/contacts/{r.json()['id']}/verify")
    r = api.call("POST", f"/api/handoffs/{h['id']}/resolve", json=DIRECTIVE)
    assert r.status_code == 200, r.text
    if case == "off_wall":  # taken off the wall after approving, before the worker runs
        SqlWallRepository(api.session, SYSTEM).remove_member(deal, "bhavesh")
        api.session.commit()
    run_worker(api)
    rows = api.session.execute(text("SELECT status, error FROM outbound_message")).all()
    assert rows == [("blocked", reason)]
    assert gmail.calls == []
    assert [a["reason"] for a in _audit(api, "outbound_blocked")] == [reason]
    if case != "off_wall":  # (bhavesh no longer sees that deal's metrics)
        m = api.call("GET", "/api/metrics").json()["outbound"]
        assert m["blocked_by_reason"] == {reason: 1} and m["outbound_without_approval"] == 0


def test_an_unverified_recipient_is_flagged_in_the_handoff(api, gmail):
    deal, party_id = _deal_with_party(api, verify=False)
    _, h = _draft_handoff(api, deal, party_id)
    assert any("not verified" in line for line in h["context_package"]["what_happened"])


# --- the MCP server re-checks every call ---------------------------------------------------------

def test_the_gmail_server_refuses_anything_but_a_matching_approval(api, gmail, monkeypatch):
    deal, party_id = _deal_with_party(api)
    _, h = _draft_handoff(api, deal, party_id)
    hid = h["id"]
    # open (unresolved), unknown, malformed
    assert gmail_server.create_gmail_draft(hid, TO, "s", "b")["reason"] == \
        "approval is not resolved"
    assert gmail_server.create_gmail_draft(99999, TO, "s", "b")["reason"] == \
        "approval not found"
    assert gmail_server.create_gmail_draft(hid, "not an email", "s", "b")["status"] == "refused"
    r = api.call("POST", f"/api/handoffs/{hid}/resolve", json={**DIRECTIVE,
                                                                "decision": "reject"})
    assert r.status_code == 200
    assert gmail_server.create_gmail_draft(hid, TO, "s", "b")["reason"] == \
        "approval decision was not 'approve'"
    assert gmail.calls == []


def test_the_gmail_server_checks_recipient_and_mode(api, gmail, monkeypatch):
    deal, party_id = _deal_with_party(api)
    _, h = _draft_handoff(api, deal, party_id)
    monkeypatch.setattr(get_settings(), "outbound_mode", "off")  # resolve without sending
    _approve(api, h)
    monkeypatch.setattr(get_settings(), "outbound_mode", "gmail_draft")
    api.session.execute(text("DELETE FROM outbound_message"))
    api.session.commit()
    assert gmail_server.create_gmail_draft(h["id"], "someone@else.com", "s", "b")["reason"] \
        == "recipient does not match the approved package"
    sent = gmail_server.send_gmail(h["id"], TO, "s", "b")
    assert sent["status"] == "refused" and "gmail_draft" in sent["reason"]
    monkeypatch.setattr(get_settings(), "outbound_mode", "off")
    assert gmail_server.create_gmail_draft(h["id"], TO, "s", "b")["status"] == "refused"
    assert gmail.calls == []
    monkeypatch.setattr(get_settings(), "outbound_mode", "gmail_draft")
    assert gmail_server.create_gmail_draft(h["id"], TO, "s", "b")["status"] == "drafted"


def test_the_real_mailer_round_trips_the_stdio_server_with_the_fake_client(tmp_path):
    """McpGmailMailer spawns gmail_server over stdio; the server reads the test database and
    uses the fake Gmail client (AURA_GMAIL_FAKE=1 is honoured only with AURA_TEST_MODE=1)."""
    url = get_settings().database_url
    engine = fresh_engine()
    with Session(engine) as s:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        s.add(UserRow(username="bhavesh", password_hash="x", role="dealmaker"))
        s.flush()
        s.add(TaskRow(id=1, deal_id=None, job_id=None, task_type="draft_email",
                      assignment_mode="human_required", status="done", created_at=now))
        s.flush()
        s.add(HandoffRow(id=1, task_id=1, deal_id=None, direction="bot_to_human",
                         trigger="policy_required", status="resolved", created_at=now,
                         context_package={"proposed_action": {"arguments": {"to_email": TO}}},
                         directive={"decision": "approve"}, resolved_by="bhavesh",
                         resolved_at=now))
        s.commit()
    log = tmp_path / "gmail.jsonl"
    env = {**os.environ, "AURA_DATABASE_URL": url, "AURA_OUTBOUND_MODE": "gmail_draft",
           "AURA_GMAIL_FAKE": "1", "AURA_TEST_MODE": "1", "AURA_GMAIL_FAKE_LOG": str(log)}
    mailer = McpGmailMailer(timeout_seconds=90, env=env)
    result = mailer.create_draft(1, TO, "Intro", "Hello Ravi")
    assert result.status == "drafted" and result.gmail_id == "fake-draft-1"
    assert result.gmail_thread_id == "fake-thread-1"
    refused = mailer.send(1, TO, "Intro", "Hello Ravi")
    assert refused.status == "refused" and "not enabled" in refused.reason
    calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert [c["kind"] for c in calls] == ["draft"] and calls[0]["to"] == TO



def test_the_fake_gmail_client_needs_the_test_flag_too(monkeypatch):
    from aura.mcp import gmail_client
    monkeypatch.setenv("AURA_GMAIL_FAKE", "1")
    monkeypatch.delenv("AURA_TEST_MODE", raising=False)
    assert isinstance(gmail_client.default_client(), gmail_client.GoogleGmailClient)
    monkeypatch.setenv("AURA_TEST_MODE", "1")
    assert isinstance(gmail_client.default_client(), gmail_client.FakeGmailClient)


# --- API: contacts, suppression, outbound, integrations ---------------------------------------

def test_contact_routes_enforce_roles_and_are_audited(api):
    p = party(api, "Roles Ltd")
    url = f"/api/parties/{p['id']}/contacts"
    assert api.call("POST", url, user="priya", json={"email": "a@b.co"}).status_code == 403
    assert api.call("POST", url, user="asha", json={"email": "not-an-email"}).status_code \
        == 422
    first = api.call("POST", url, user="asha", json={"email": "a@b.co"}).json()
    assert first["is_primary"] is True  # a party's first contact is its primary
    assert api.call("POST", url, user="asha", json={"email": "A@B.co"}).status_code == 409
    second = api.call("POST", url, user="asha", json={"email": "c@b.co",
                                                      "is_primary": True}).json()
    listed = {c["email"]: c["is_primary"] for c in api.call("GET", url, user="priya").json()}
    assert listed == {"a@b.co": False, "c@b.co": True}
    verify = f"/api/parties/contacts/{second['id']}/verify"
    assert api.call("POST", verify, user="asha").status_code == 403
    assert api.call("POST", verify).json()["verified_at"] is not None
    assert api.call("DELETE", f"{url}/{first['id']}", user="asha").status_code == 204
    assert api.call("GET", url, user="admin").status_code == 403
    actions = {a for (a,) in api.session.execute(text(
        "SELECT action FROM audit_entries WHERE action LIKE 'contact_%'"))}
    assert actions == {"contact_added", "contact_verified", "contact_removed"}
    with pytest.raises(Exception):  # the database refuses a malformed address too
        api.session.execute(text("INSERT INTO party_contact (party_id, name, email, is_primary,"
                                 " created_by, created_at) VALUES (:p, '', 'Bad Address', 0,"
                                 " 'x', '2026-10-07')"), {"p": p["id"]})
    api.session.rollback()


def test_suppression_routes(api):
    assert api.call("GET", "/api/suppression", user="asha").status_code == 403
    r = api.call("POST", "/api/suppression", user="priya",
                 json={"kind": "domain", "value": "spam.example", "reason": "no"})
    assert r.status_code == 201
    assert api.call("POST", "/api/suppression", json={"kind": "domain",
                                                      "value": "SPAM.example"}).status_code \
        == 409
    assert api.call("POST", "/api/suppression", json={"kind": "email",
                                                      "value": "nope"}).status_code == 422
    assert [e["value"] for e in api.call("GET", "/api/suppression").json()] == ["spam.example"]
    assert api.call("DELETE", f"/api/suppression/{r.json()['id']}",
                    user="priya").status_code == 204
    assert {a["kind"] for a in _audit(api, "suppression_added")} == {"domain"}
    assert len(_audit(api, "suppression_removed")) == 1


def test_outbound_list_is_wall_filtered(api, gmail):
    deal, party_id = _deal_with_party(api)
    _, h = _draft_handoff(api, deal, party_id)
    _approve(api, h)
    assert len(_outbound(api)) == 1
    assert api.call("GET", "/api/outbound", user="asha").json() == []  # not on the wall


def test_gmail_integration_status_never_carries_a_token(api, monkeypatch):
    app.dependency_overrides[get_mailer_status] = lambda: MailerStatus(
        connected=True, account_email="desk@example.com",
        scopes=("https://www.googleapis.com/auth/gmail.compose",), storage="keyring")
    assert api.call("GET", "/api/integrations/gmail", user="asha").status_code == 403
    assert api.call("GET", "/api/integrations/gmail", user="priya").status_code == 403
    body = api.call("GET", "/api/integrations/gmail", user="admin").json()
    assert body["connected"] is True and body["account_email"] == "desk@example.com"
    assert body["mode"] == get_settings().outbound_mode
    assert body["connect_command"] == "uv run python -m aura.mcp.gmail_auth"
    assert not {"token", "refresh_token", "client_secret"} & set(body)
    assert api.call("GET", "/api/integrations/gmail").status_code == 200


def test_token_store_round_trip_and_status_hide_secrets(monkeypatch, tmp_path):
    class MemoryKeyring:
        def __init__(self):
            self.data = {}

        def get_password(self, service, key):
            return self.data.get((service, key))

        def set_password(self, service, key, value):
            self.data[(service, key)] = value

        def delete_password(self, service, key):
            self.data.pop((service, key), None)

    kr = MemoryKeyring()
    monkeypatch.setattr(gmail_auth, "_keyring", lambda: kr)
    monkeypatch.setattr(get_settings(), "gmail_token_file", str(tmp_path / "gmail_token.enc"))
    assert gmail_auth.stored_status().connected is False
    record = {"credentials": {"token": "SECRET-ACCESS", "refresh_token": "SECRET-REFRESH",
                              "client_secret": "SECRET-CLIENT",
                              "scopes": [gmail_auth.SCOPE_URLS["compose"]],
                              "expiry": "2026-10-07T10:00:00Z"},
              "account": "desk@example.com"}
    assert gmail_auth.save_record(record) == "keyring"
    status = gmail_auth.stored_status()
    assert status.connected and status.account_email == "desk@example.com"
    assert "SECRET" not in repr(status)
    gmail_auth.mark_needs_reconnect("RefreshError")
    assert gmail_auth.stored_status().needs_reconnect is True
    assert gmail_auth.delete_record() is True and gmail_auth.stored_status().connected is False

    # No keyring: the record is written encrypted, never in clear text.
    monkeypatch.setattr(gmail_auth, "_keyring", lambda: None)
    assert gmail_auth.save_record(record) == "encrypted_file"
    assert b"SECRET" not in (tmp_path / "gmail_token.enc").read_bytes()
    assert gmail_auth.stored_status().storage == "encrypted_file"
    gmail_auth.delete_record()
    assert not (tmp_path / "gmail_token.enc").exists()


