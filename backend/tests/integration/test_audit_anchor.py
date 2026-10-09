"""Audit: every mutation is on the chain, the anchor catches tail deletion (GL2, F9, C4)."""
import json
from datetime import datetime, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from aura.config import BACKEND_DIR, get_settings
from aura.core.domain.audit import AuditEntry
from aura.data.repositories.sql import SqlAuditRepository
from aura.data.verify_audit import (default_anchor_path, read_anchor, refresh_anchor, verify,
                                    write_anchor)
from aura.data.walls import SYSTEM
from tests.integration.pgtest import fresh_engine
from tests.integration.conftest import PASSWORDS  # noqa: F401  (documents who exists)
from tests.integration.helpers import (DIRECTIVE, link, make_deal, mark_executed, move, party,
                                       run_worker, set_stage, submit, tamper_audit, upload)


@pytest.fixture()
def session():
    engine = fresh_engine()
    with Session(engine) as s:
        yield s


def _append(session, n, start=0):
    repo = SqlAuditRepository(session, SYSTEM)
    for i in range(start, start + n):
        repo.append(AuditEntry(id=None, job_id=None, actor="u", action=f"a{i}",
                               payload={"i": i}, created_at=datetime.now(timezone.utc)))
    session.commit()


# ------------------------------------------------------------------ the anchor file

def test_no_anchor_yet_is_fine_and_refresh_writes_one(session, tmp_path):
    anchor = tmp_path / "audit_anchor.json"
    _append(session, 3)
    first = verify(session, anchor)
    assert first.ok and first.anchor.head_id is None and first.anchor.ok

    done = refresh_anchor(session, anchor)
    assert done.ok and done.anchor.head_id == 3 and done.anchor.ok
    body = json.loads(anchor.read_text())
    assert set(body) == {"head_id", "head_hash", "written_at"}
    head = session.execute(text("SELECT id, row_hash FROM audit_entries ORDER BY id DESC "
                                "LIMIT 1")).one()
    assert body["head_id"] == head[0] == 3 and body["head_hash"] == head[1]
    assert datetime.fromisoformat(body["written_at"])


def test_the_anchor_follows_new_entries_but_never_moves_back(session, tmp_path):
    anchor = tmp_path / "a.json"
    _append(session, 2)
    refresh_anchor(session, anchor)
    _append(session, 3, start=2)
    assert verify(session, anchor).ok  # growth is fine: the anchored row is still there
    assert refresh_anchor(session, anchor).anchor.head_id == 5


def test_tail_deletion_is_caught_by_the_anchor_though_the_chain_still_verifies(session,
                                                                              tmp_path):
    anchor = tmp_path / "a.json"
    _append(session, 4)
    refresh_anchor(session, anchor)
    tamper_audit(session, "DELETE FROM audit_entries WHERE id = 4")
    from aura.data.verify_audit import verify_chain
    assert verify_chain(session) is None  # the remaining chain is internally consistent

    result = verify(session, anchor)
    assert result.ok is False and result.broken_at == 4  # the first id that should exist
    assert result.anchor.ok is False and result.anchor.head_id == 4
    assert "tail deleted" in result.message
    # and a refresh refuses to move the anchor onto the shortened chain
    refresh_anchor(session, anchor)
    assert read_anchor(anchor)["head_id"] == 4


def test_deleting_everything_is_caught_too(session, tmp_path):
    anchor = tmp_path / "a.json"
    _append(session, 2)
    refresh_anchor(session, anchor)
    tamper_audit(session, "DELETE FROM audit_entries")
    result = verify(session, anchor)
    assert result.ok is False and result.broken_at == 1 and result.anchor.ok is False


def test_replacing_the_tail_with_new_rows_is_caught_by_the_hash(session, tmp_path):
    anchor = tmp_path / "a.json"
    _append(session, 3)
    refresh_anchor(session, anchor)
    # the attacker also winds the id sequence back, so the replacement reuses id 3
    tamper_audit(session, "DELETE FROM audit_entries WHERE id = 3",
                 "SELECT setval(pg_get_serial_sequence('audit_entries', 'id'), 2)")
    _append(session, 1, start=99)  # a fresh row 3 with a different hash
    assert session.execute(text("SELECT MAX(id) FROM audit_entries")).scalar() == 3
    result = verify(session, anchor)
    assert result.ok is False and result.anchor.ok is False and result.broken_at == 3


def test_editing_a_row_breaks_the_chain_at_that_row(session, tmp_path):
    anchor = tmp_path / "a.json"
    _append(session, 4)
    refresh_anchor(session, anchor)
    tamper_audit(session, "UPDATE audit_entries SET actor = 'mallory' WHERE id = 2")
    result = verify(session, anchor)
    assert result.ok is False and result.broken_at == 2


def test_an_unreadable_anchor_is_a_failure_not_an_absence(session, tmp_path):
    anchor = tmp_path / "a.json"
    _append(session, 1)
    anchor.write_text("not json")
    result = verify(session, anchor)
    assert result.ok is False and result.anchor.ok is False and "unreadable" in result.message
    anchor.write_text(json.dumps({"head_id": "x"}))
    assert verify(session, anchor).ok is False


def test_an_empty_chain_with_an_anchor_none_is_ok(session, tmp_path):
    assert verify(session, tmp_path / "missing.json").ok
    assert verify(session, None).ok


def test_write_anchor_is_atomic_and_creates_the_directory(tmp_path):
    target = tmp_path / "nested" / "dir" / "audit_anchor.json"
    write_anchor(target, 7, "ab" * 32)
    assert read_anchor(target)["head_id"] == 7
    assert not list(target.parent.glob("*.tmp"))


def test_default_anchor_path_is_per_database(monkeypatch, tmp_path):
    def cfg(**env):
        for key in ("AURA_DATABASE_URL", "AURA_AUDIT_ANCHOR_PATH"):
            monkeypatch.delenv(key, raising=False)
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        get_settings.cache_clear()
        return default_anchor_path()

    pg = "postgresql+psycopg://aura_app:pw@127.0.0.1:5433/"
    try:
        assert cfg(AURA_DATABASE_URL=pg + "aura") == BACKEND_DIR / "data" / "audit_anchor.json"
        scratch = cfg(AURA_DATABASE_URL=pg + "aura_scratch")
        assert scratch == BACKEND_DIR / "data" / "audit_anchor.aura_scratch.json"  # not aura's
        explicit = (tmp_path / "x.json").as_posix()
        assert cfg(AURA_DATABASE_URL=pg + "aura_scratch",
                   AURA_AUDIT_ANCHOR_PATH=explicit).as_posix() == explicit
    finally:
        get_settings.cache_clear()


# ------------------------------------------------------------------ the API

def test_verify_endpoint_shape_and_anchor_detection(api, tmp_path):
    make_deal(api)
    first = api.call("GET", "/api/audit/verify").json()
    assert first == {"ok": True, "broken_at": None,
                     "anchor": {"head_id": None, "head_hash": None, "written_at": None,
                                "ok": True}}
    anchor = tmp_path / "audit_anchor.json"
    refresh_anchor(api.session, anchor)
    head = api.session.execute(text("SELECT id, row_hash FROM audit_entries ORDER BY id DESC "
                                    "LIMIT 1")).one()
    ok = api.call("GET", "/api/audit/verify").json()
    assert ok["ok"] is True and ok["broken_at"] is None
    assert ok["anchor"]["head_id"] == head[0] and ok["anchor"]["head_hash"] == head[1]
    assert ok["anchor"]["ok"] is True and ok["anchor"]["written_at"]

    tamper_audit(api.session, "DELETE FROM audit_entries WHERE id = :i", params={"i": head[0]})
    bad = api.call("GET", "/api/audit/verify").json()
    assert bad["ok"] is False and bad["broken_at"] == head[0]
    assert bad["anchor"]["ok"] is False and bad["anchor"]["head_id"] == head[0]


def test_activity_exposes_the_hash_chain_and_deal_id(api):
    deal = make_deal(api)
    upload(api, deal)
    rows = api.call("GET", "/api/activity").json()
    assert {"id", "job_id", "deal_id", "actor", "action", "payload", "created_at", "prev_hash",
            "row_hash"} <= set(rows[0])
    oldest_first = sorted(rows, key=lambda r: r["id"])
    assert oldest_first[0]["prev_hash"] == "0" * 64
    for a, b in zip(oldest_first, oldest_first[1:]):
        assert b["prev_hash"] == a["row_hash"]
    assert all(len(r["row_hash"]) == 64 for r in rows) and rows[0]["deal_id"] == deal
    summary = api.call("GET", "/api/dashboard/summary").json()["recent_activity"]
    assert all(r["row_hash"] and r["prev_hash"] for r in summary)


# ------------------------------------------------------------------ every mutation is audited

def _actions(api):
    return api.session.execute(text("SELECT action FROM audit_entries ORDER BY id")
                               ).scalars().all()


def _check(api, expected, call):
    before = len(_actions(api))
    call()
    new = _actions(api)[before:]
    assert expected in new, (expected, new)
    return new


def test_every_mutation_leaves_an_audit_row(api):
    deal = make_deal(api)
    _check(api, "deal_created", lambda: make_deal(api, "AUD-2"))
    p = {}
    _check(api, "party_created", lambda: p.update(party(api)))
    _check(api, "party_linked", lambda: link(api, deal, p["id"], "buyer"))
    _check(api, "mandate_created", lambda: api.call(
        "POST", f"/api/deals/{deal}/mandates", json={"title": "m", "side": "raise"}))
    doc = {}
    _check(api, "document_uploaded", lambda: doc.update(upload(api, deal)))
    _check(api, "document_uploaded", lambda: upload(api, deal))  # a new version
    _check(api, "document_updated", lambda: mark_executed(api, doc["id"]))
    _check(api, "document_viewed", lambda: api.call("GET", f"/api/documents/{doc['id']}"))
    _check(api, "document_downloaded", lambda: api.call(
        "GET", f"/api/documents/{doc['id']}/download"))
    cp = {}
    _check(api, "condition_created", lambda: cp.update(api.call(
        "POST", f"/api/deals/{deal}/conditions",
        json={"description": "x", "cp_type": "y"}).json()))
    _check(api, "condition_updated", lambda: api.call(
        "PATCH", f"/api/conditions/{cp['id']}", json={"status": "in_progress"}))
    api.session.execute(text(
        "INSERT INTO diligence_item (deal_id, prompt, severity, status, evidence_doc_ids) "
        "VALUES (:d, 'p', 'standard', 'open', '[]')"), {"d": deal})
    api.session.commit()
    item = api.session.execute(text("SELECT MAX(id) FROM diligence_item")).scalar()
    _check(api, "diligence_updated", lambda: api.call(
        "PATCH", f"/api/diligence/{item}", json={"status": "requested"}))
    _check(api, "finding_created", lambda: api.call(
        "POST", f"/api/deals/{deal}/findings",
        json={"diligence_item_id": item, "finding_type": "observation", "description": "d",
              "affects_valuation": False}))
    _check(api, "deal_flags_updated", lambda: api.call(
        "PATCH", f"/api/deals/{deal}", json={"regulatory_flags": ["SEBI"]}))
    _check(api, "deal_signoff", lambda: api.call(
        "POST", f"/api/deals/{deal}/signoffs", user="priya", json={"note": "ok"}))
    _check(api, "wall_member_added", lambda: api.add_member(deal, "asha"))
    _check(api, "wall_member_removed", lambda: api.call(
        "DELETE", f"/api/deals/{deal}/members", user="priya", json={"username": "asha"}))
    set_stage(api, deal, "QUALIFIED")
    _check(api, "deal_transition_blocked", lambda: move(api, deal, "MANDATED"))
    _check(api, "deal_transition", lambda: move(
        api, deal, "MANDATED", override_justification="signed on paper"))
    _check(api, "user_created", lambda: api.call("POST", "/api/users", user="admin", json={
        "username": "ravi", "password": "longenough", "role": "analyst"}))
    uid = api.session.execute(text("SELECT id FROM users WHERE username = 'ravi'")).scalar()
    _check(api, "user_updated", lambda: api.call("PATCH", f"/api/users/{uid}", user="admin",
                                                  json={"active": False}))
    _check(api, "job_submitted", lambda: submit(api, {"brief": "x"}, deal_id=deal))
    _check(api, "handoff_created", lambda: run_worker(api))
    (h,) = api.call("GET", "/api/handoffs").json()
    _check(api, "handoff_resolved", lambda: api.call(
        "POST", f"/api/handoffs/{h['id']}/resolve", json=DIRECTIVE))
    assert api.call("GET", "/api/audit/verify").json()["ok"] is True  # all of it on the chain


def test_audit_rows_name_the_deal_so_walls_filter_them(api):
    deal = make_deal(api)
    upload(api, deal)
    link(api, deal, party(api)["id"], "buyer")
    mine = api.call("GET", "/api/activity").json()
    assert {r["deal_id"] for r in mine if r["action"] in (
        "document_uploaded", "party_linked", "deal_created")} == {deal}
    assert [r for r in api.call("GET", "/api/activity", user="asha").json()
            if r["deal_id"] == deal] == []


# ------------------------------------------------------------------ rejected handoffs

def _bad_handoff(api, **extra):
    return api.call("POST", "/api/handoffs", json={
        "task_type": "chase", "context_package": {"what_happened": []}, **extra})


def test_a_422_handoff_rejection_is_audited_and_survives_the_rollback(api):
    deal = make_deal(api)
    r = _bad_handoff(api, deal_id=deal)
    assert r.status_code == 422
    row = api.session.execute(text("SELECT actor, deal_id, payload FROM audit_entries WHERE "
                                   "action = 'handoff_rejected'")).one()
    assert row[0] == "bhavesh" and row[1] == deal
    assert "decision_required" in row[2]["reason"]
    assert api.session.execute(text("SELECT COUNT(*) FROM handoff")).scalar() == 0
    assert api.session.execute(text("SELECT COUNT(*) FROM task")).scalar() == 0
    assert api.call("GET", "/api/audit/verify").json()["ok"] is True


def test_a_rejected_directive_is_audited_and_the_handoff_stays_open(api):
    deal = make_deal(api)
    submit(api, {"brief": "x"}, deal_id=deal)
    run_worker(api)
    (h,) = api.call("GET", "/api/handoffs").json()
    r = api.call("POST", f"/api/handoffs/{h['id']}/resolve", json={"decision": "approve"})
    assert r.status_code == 422
    row = api.session.execute(text("SELECT payload FROM audit_entries WHERE action = "
                                   "'handoff_rejected'")).scalar()
    assert row["handoff_id"] == h["id"]
    assert api.call("GET", f"/api/handoffs/{h['id']}").json()["status"] == "open"
    bad = api.call("POST", f"/api/handoffs/{h['id']}/resolve",
                   json={**DIRECTIVE, "decision": "maybe"})
    assert bad.status_code == 422
    assert _actions(api).count("handoff_rejected") == 2


def test_forbidden_attempts_write_nothing(api):
    deal = make_deal(api)
    submit(api, {"brief": "x"}, deal_id=deal)
    run_worker(api)
    (h,) = api.call("GET", "/api/handoffs").json()
    before = len(_actions(api))
    assert api.call("POST", f"/api/handoffs/{h['id']}/resolve", user="admin",
                    json=DIRECTIVE).status_code == 403
    assert len(_actions(api)) == before