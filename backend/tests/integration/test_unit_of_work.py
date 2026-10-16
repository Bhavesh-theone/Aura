"""Each service call is one transaction: a failure midway leaves no partial writes."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from aura.api.main import app
from aura.core.domain.errors import GuardBlocked
from aura.data.repositories import sql_deals
from aura.data.repositories.sql import SqlAuditRepository
from aura.data.uow import SqlUnitOfWork


def _count(api, table):
    return api.session.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()


def _deal_at(api, stage):
    r = api.call("POST", "/api/deals", json={"external_id": "U-1", "name": "UoW",
                                             "transaction_class": "DEBT"})
    deal_id = r.json()["id"]
    api.session.execute(text("UPDATE deals SET stage = :s WHERE id = :i"),
                        {"s": stage, "i": deal_id})
    api.session.commit()
    return deal_id


@pytest.fixture()
def crashing(api):
    """A client that turns server errors into 500 responses instead of raising."""
    return TestClient(app, raise_server_exceptions=False)


def test_failure_midway_through_a_transition_leaves_no_partial_writes(api, crashing,
                                                                      monkeypatch):
    deal_id = _deal_at(api, "NEGOTIATION")
    doc = api.call("POST", f"/api/deals/{deal_id}/documents",
                   files={"file": ("t.pdf", b"x")}, data={"doc_class": "term_sheet"}).json()
    api.call("PATCH", f"/api/documents/{doc['id']}", json={"is_executed": True})
    before = {t: _count(api, t) for t in ("deal_stage_history", "audit_entries",
                                          "stage_guard_evaluation", "diligence_item")}

    real_add = sql_deals.SqlDiligenceRepository.add_item
    calls = []

    def add_item_then_die(self, item):
        calls.append(item.prompt)
        if len(calls) == 3:
            raise RuntimeError("disk fell over")
        return real_add(self, item)

    monkeypatch.setattr(sql_deals.SqlDiligenceRepository, "add_item", add_item_then_die)
    r = crashing.post(f"/api/deals/{deal_id}/transition", json={"to_stage": "DILIGENCE"},
                      headers=api.as_user("bhavesh"))
    assert r.status_code == 500 and len(calls) == 3  # two items were already written

    after = {t: _count(api, t) for t in before}
    assert after == before
    assert api.session.execute(text("SELECT stage FROM deals WHERE id = :i"),
                               {"i": deal_id}).scalar() == "NEGOTIATION"

    # the same request, once the fault is gone, succeeds in full
    monkeypatch.setattr(sql_deals.SqlDiligenceRepository, "add_item", real_add)
    ok = api.call("POST", f"/api/deals/{deal_id}/transition", json={"to_stage": "DILIGENCE"})
    assert ok.status_code == 200
    assert _count(api, "diligence_item") == 7


def test_failure_during_document_upload_leaves_no_document_row(api, crashing, monkeypatch):
    deal_id = _deal_at(api, "ORIGINATED")
    docs, audits = _count(api, "document"), _count(api, "audit_entries")

    real_append = SqlAuditRepository.append

    def append(self, entry):
        if entry.action == "document_uploaded":
            raise RuntimeError("audit store unavailable")
        return real_append(self, entry)

    monkeypatch.setattr(SqlAuditRepository, "append", append)
    r = crashing.post(f"/api/deals/{deal_id}/documents", files={"file": ("a.pdf", b"x")},
                      data={"doc_class": "nda"}, headers=api.as_user("bhavesh"))
    assert r.status_code == 500
    assert _count(api, "document") == docs and _count(api, "audit_entries") == audits


def test_a_domain_error_rolls_back_too(api):
    deal_id = _deal_at(api, "ORIGINATED")
    n = _count(api, "deal_stage_history")
    assert api.call("POST", f"/api/deals/{deal_id}/transition",
                    json={"to_stage": "MATCHED"}).status_code == 409
    assert _count(api, "deal_stage_history") == n


def test_a_blocked_guard_keeps_its_evaluation_rows(api):
    """GuardBlocked declares persist_writes: the failed attempt is itself the record."""
    deal_id = _deal_at(api, "QUALIFIED")
    r = api.call("POST", f"/api/deals/{deal_id}/transition", json={"to_stage": "MANDATED"})
    assert r.status_code == 409
    assert _count(api, "stage_guard_evaluation") == 1  # T2 only: the move has one guard
    actions = [a for (a,) in api.session.execute(text("SELECT action FROM audit_entries"))]
    assert "deal_transition_blocked" in actions


def test_events_are_held_until_commit_and_dropped_on_rollback(api):
    class Sink:
        def __init__(self):
            self.got = []

        def publish(self, event_type, payload):
            self.got.append(event_type)

    sink = Sink()
    uow = SqlUnitOfWork(api.session)
    events = uow.defer(sink)
    events.publish("a", {})
    assert sink.got == []
    uow.commit()
    assert sink.got == ["a"]

    events.publish("b", {})
    with pytest.raises(RuntimeError):
        with uow.transaction():
            raise RuntimeError("nope")
    assert sink.got == ["a"]

    with pytest.raises(GuardBlocked):
        with uow.transaction():
            events.publish("c", {})
            raise GuardBlocked("blocked", [])
    assert sink.got == ["a", "c"]
