"""The event feed (X2 support): entity_changed on every mutation, delivered only to the
users on the deal's wall."""
import asyncio
from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from aura.api import deps
from aura.api.ws.hub import EventHub
from aura.core.domain.audit import AuditEntry
from aura.core.policy.entity_policy import ENTITY_KINDS, entity_kind_for
from aura.core.services.notifying_audit import NotifyingAudit
from aura.worker.runner import run_once
from aura.worker.stub_orchestrator import StubOrchestrator
from tests.integration.helpers import (DIRECTIVE, link, make_deal, mark_executed, move, party,
                                       run_worker, set_stage, submit, upload)
from tests.unit.fakes import FakeAuditRepo, FakeEvents


class FakeSocket:
    def __init__(self):
        self.sent, self.accepted = [], False

    async def accept(self):
        self.accepted = True

    async def send_json(self, message):
        self.sent.append(message)


def _fanout(hub, event_type, payload, sockets):
    async def go():
        loop = asyncio.get_running_loop()
        hub.bind_loop(loop)
        for username, ws in sockets.items():
            await hub.connect(ws, username)
        hub.publish(event_type, payload)
        await asyncio.sleep(0.05)
    asyncio.run(go())


def test_a_deal_event_reaches_only_users_on_that_deals_wall():
    walls = {1: {"bhavesh", "priya"}, 2: {"asha"}}
    hub = EventHub(members_for_deal=lambda deal_id: walls[deal_id])
    sockets = {name: FakeSocket() for name in ("bhavesh", "asha", "priya", "admin")}
    _fanout(hub, "entity_changed", {"kind": "document", "deal_id": 1}, sockets)
    got = {name: ws.sent for name, ws in sockets.items()}
    assert got["bhavesh"] == got["priya"] == [
        {"type": "entity_changed", "payload": {"kind": "document", "deal_id": 1}}]
    assert got["asha"] == [] and got["admin"] == []  # not on the wall, whatever the role


def test_an_event_about_no_deal_reaches_everyone():
    hub = EventHub(members_for_deal=lambda deal_id: set())
    sockets = {name: FakeSocket() for name in ("bhavesh", "asha")}
    _fanout(hub, "job_submitted", {"job_id": 3, "deal_id": None}, sockets)
    assert all(len(ws.sent) == 1 for ws in sockets.values())


def test_if_the_wall_cannot_be_read_the_event_is_dropped_not_broadcast():
    def boom(deal_id):
        raise RuntimeError("db down")
    hub = EventHub(members_for_deal=boom)
    sockets = {"bhavesh": FakeSocket()}
    _fanout(hub, "entity_changed", {"kind": "deal", "deal_id": 1}, sockets)
    assert sockets["bhavesh"].sent == []


def test_a_user_who_leaves_the_wall_stops_hearing_about_it():
    members = {1: {"bhavesh", "asha"}}
    hub = EventHub(members_for_deal=lambda deal_id: members[deal_id])
    sockets = {"asha": FakeSocket()}
    _fanout(hub, "entity_changed", {"kind": "deal", "deal_id": 1}, sockets)
    assert len(sockets["asha"].sent) == 1
    members[1].discard("asha")
    _fanout(hub, "entity_changed", {"kind": "deal", "deal_id": 1}, sockets)
    assert len(sockets["asha"].sent) == 1


def test_the_real_wall_lookup_reads_the_database(api, monkeypatch):
    deal = make_deal(api)
    api.add_member(deal, "asha")
    monkeypatch.setattr("aura.data.engine.SessionLocal", lambda: api.session)
    monkeypatch.setattr(api.session, "close", lambda: None)
    from aura.api.ws.hub import wall_usernames
    assert wall_usernames(deal) == {"bhavesh", "priya", "asha"}


# ------------------------------------------------------------------ entity_changed

def test_every_audited_action_maps_to_a_known_kind_or_none():
    for action in ("deal_created", "document_uploaded", "diligence_updated", "finding_created",
                   "extraction_verified", "deal_signoff", "handoff_resolved", "job_submitted",
                   "condition_updated"):
        assert entity_kind_for(action) in ENTITY_KINDS
    for action in ("user_created", "document_viewed", "handoff_rejected", "nonsense"):
        assert entity_kind_for(action) is None


def test_the_notifying_audit_announces_each_change_with_its_deal():
    inner, events = FakeAuditRepo(), FakeEvents()
    audit = NotifyingAudit(inner, events)
    audit.append(AuditEntry(id=None, job_id=None, deal_id=7, actor="u", action="document_uploaded",
                            payload={}, created_at=datetime.now(timezone.utc)))
    audit.append(AuditEntry(id=None, job_id=None, deal_id=7, actor="u", action="user_created",
                            payload={}, created_at=datetime.now(timezone.utc)))
    assert events.published == [("entity_changed", {"kind": "document", "deal_id": 7})]
    assert len(inner.entries) == 2 and audit.count_by_action("user_created") == 1


class Recorder:
    def __init__(self):
        self.got = []

    def publish(self, event_type, payload):
        self.got.append((event_type, payload))


@pytest.fixture()
def feed(api, monkeypatch):
    recorder = Recorder()
    monkeypatch.setattr(deps, "hub", recorder)
    return recorder


def _changed(feed):
    return {(p["kind"], p["deal_id"]) for t, p in feed.got if t == "entity_changed"}


def test_each_kind_of_mutation_emits_entity_changed_for_its_deal(api, feed):
    deal = make_deal(api)
    assert ("deal", deal) in _changed(feed)
    doc = upload(api, deal)
    assert ("document", deal) in _changed(feed)
    mark_executed(api, doc["id"])
    link(api, deal, party(api)["id"], "buyer")
    api.session.execute(text(
        "INSERT INTO diligence_item (deal_id, prompt, severity, status, evidence_doc_ids) "
        "VALUES (:d, 'p', 'standard', 'open', '[]')"), {"d": deal})
    api.session.commit()
    item = api.session.execute(text(
        "SELECT MAX(id) FROM diligence_item")).scalar()
    api.call("PATCH", f"/api/diligence/{item}", json={"status": "requested"})
    assert ("diligence", deal) in _changed(feed)
    api.call("POST", f"/api/deals/{deal}/findings", json={
        "diligence_item_id": item, "finding_type": "observation", "description": "d",
        "affects_valuation": False})
    assert ("finding", deal) in _changed(feed)
    cp = api.call("POST", f"/api/deals/{deal}/conditions",
                  json={"description": "x", "cp_type": "y"}).json()
    api.call("PATCH", f"/api/conditions/{cp['id']}", json={"status": "in_progress"})
    assert ("condition", deal) in _changed(feed)
    api.call("POST", f"/api/deals/{deal}/signoffs", user="priya", json={"note": "ok"})
    assert ("signoff", deal) in _changed(feed)
    submit(api, {"brief": "x"}, deal_id=deal)
    assert ("job", deal) in _changed(feed)

    feed.got.clear()
    run_worker_events = Recorder()
    run_once(api.session, StubOrchestrator(), run_worker_events)
    assert ("handoff", deal) in {(p["kind"], p["deal_id"]) for t, p in run_worker_events.got
                                 if t == "entity_changed"}
    (h,) = api.call("GET", "/api/handoffs").json()
    api.call("POST", f"/api/handoffs/{h['id']}/resolve", json=DIRECTIVE)
    assert ("handoff", deal) in _changed(feed)


def test_the_existing_events_carry_their_deal_id_so_they_can_be_walled(api, feed):
    deal = make_deal(api)
    submit(api, {"brief": "x"}, deal_id=deal)
    named = {t: p for t, p in feed.got if t == "job_submitted"}
    assert named["job_submitted"]["deal_id"] == deal
    run_worker(api)
    (h,) = api.call("GET", "/api/handoffs").json()
    feed.got.clear()
    api.call("POST", f"/api/handoffs/{h['id']}/resolve", json=DIRECTIVE)
    resolved = [p for t, p in feed.got if t == "handoff_resolved"]
    assert resolved and resolved[0]["deal_id"] == deal and resolved[0]["handoff_id"] == h["id"]


def test_a_failed_request_publishes_nothing(api, feed):
    deal = make_deal(api)
    feed.got.clear()
    assert move(api, deal, "MATCHED").status_code == 409  # not a legal move
    assert api.call("POST", f"/api/deals/{deal}/transition", user="asha",
                    json={"to_stage": "QUALIFIED"}).status_code == 403
    assert feed.got == []


def test_a_blocked_transition_still_announces_its_recorded_attempt(api, feed):
    deal = make_deal(api)
    set_stage(api, deal, "QUALIFIED")
    feed.got.clear()
    assert move(api, deal, "MANDATED").status_code == 409
    assert ("deal", deal) in _changed(feed)  # the evaluation rows were kept, so tell people