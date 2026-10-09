"""Roles (PRD R3): dealmaker, analyst, compliance and admin, enforced in the core services."""
import json

import pytest
from sqlalchemy import text

from tests.integration.helpers import (DIRECTIVE, link, make_deal, move, party, run_worker,
                                       set_stage, submit, upload)


def _login(api, username, password):
    return api.client.post("/api/auth/login", json={"username": username,
                                                    "password": password})


@pytest.mark.parametrize("username, role", [("bhavesh", "dealmaker"), ("asha", "analyst"),
                                            ("priya", "compliance"), ("admin", "admin")])
def test_seeded_users_log_in_and_me_reports_the_role(api, username, role):
    me = api.call("GET", "/api/auth/me", user=username).json()
    assert set(me) == {"id", "username", "role"}
    assert me["username"] == username and me["role"] == role


# ----------------------------------------------------------------- user management

def test_only_admin_manages_users(api):
    for user in ("bhavesh", "asha", "priya"):
        assert api.call("GET", "/api/users", user=user).status_code == 403
        assert api.call("POST", "/api/users", user=user, json={
            "username": "x", "password": "longenough", "role": "analyst"}).status_code == 403
        assert api.call("PATCH", "/api/users/1", user=user,
                        json={"active": False}).status_code == 403
    users = api.call("GET", "/api/users", user="admin").json()
    assert [(u["username"], u["role"], u["active"]) for u in users] == [
        ("bhavesh", "dealmaker", True), ("asha", "analyst", True),
        ("priya", "compliance", True), ("admin", "admin", True)]
    assert set(users[0]) == {"id", "username", "role", "active"}


def test_admin_creates_users_who_can_log_in_with_their_role(api):
    r = api.call("POST", "/api/users", user="admin", json={
        "username": "ravi", "password": "ravi-pass-1", "role": "compliance"})
    assert r.status_code == 201
    assert r.json()["username"] == "ravi" and r.json()["role"] == "compliance"
    assert r.json()["active"] is True and "password" not in r.json()
    assert "password_hash" not in r.text
    token = _login(api, "ravi", "ravi-pass-1").json()["access_token"]
    me = api.client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).json()
    assert me["role"] == "compliance"
    stored = api.session.execute(text("SELECT password_hash FROM users WHERE username = "
                                      "'ravi'")).scalar()
    assert stored != "ravi-pass-1" and stored.startswith("$2")


@pytest.mark.parametrize("body, status", [
    ({"username": "asha", "password": "longenough", "role": "analyst"}, 409),
    ({"username": "new", "password": "short", "role": "analyst"}, 422),
    ({"username": "new", "password": "longenough", "role": "member"}, 422),
    ({"username": "bad name!", "password": "longenough", "role": "analyst"}, 422),
    ({"username": "", "password": "longenough", "role": "analyst"}, 422),
])
def test_user_creation_is_validated(api, body, status):
    assert api.call("POST", "/api/users", user="admin", json=body).status_code == status


def test_admin_changes_roles_and_role_changes_apply_immediately(api):
    deal = make_deal(api)
    assert upload(api, deal, user="bhavesh")  # sanity: a dealmaker uploads
    api.add_member(deal, "asha")
    asha_id = api.session.execute(text("SELECT id FROM users WHERE username = 'asha'")).scalar()
    assert api.call("POST", f"/api/deals/{deal}/documents", user="asha",
                    files={"file": ("a.pdf", b"x")},
                    data={"doc_class": "nda"}).status_code == 201

    r = api.call("PATCH", f"/api/users/{asha_id}", user="admin", json={"role": "compliance"})
    assert r.status_code == 200 and r.json()["role"] == "compliance"
    # asha's existing token now carries a compliance user: she may not upload any more
    assert api.call("POST", f"/api/deals/{deal}/documents", user="asha",
                    files={"file": ("b.pdf", b"x")},
                    data={"doc_class": "nda"}).status_code == 403
    assert api.call("PATCH", f"/api/users/999", user="admin",
                    json={"role": "analyst"}).status_code == 404
    assert api.call("PATCH", f"/api/users/{asha_id}", user="admin",
                    json={"role": "member"}).status_code == 422


def test_inactive_users_cannot_log_in_and_lose_their_session(api):
    assert api.call("GET", "/api/auth/me", user="asha").status_code == 200  # has a token
    asha_id = api.session.execute(text("SELECT id FROM users WHERE username = 'asha'")).scalar()
    r = api.call("PATCH", f"/api/users/{asha_id}", user="admin", json={"active": False})
    assert r.status_code == 200 and r.json()["active"] is False
    assert _login(api, "asha", "analyst123").status_code == 401
    assert api.call("GET", "/api/auth/me", user="asha").status_code == 401
    api.call("PATCH", f"/api/users/{asha_id}", user="admin", json={"active": True})
    assert _login(api, "asha", "analyst123").status_code == 200


def test_the_last_active_admin_cannot_be_demoted_or_deactivated(api):
    admin_id = api.session.execute(text("SELECT id FROM users WHERE username = 'admin'")
                                   ).scalar()
    assert api.call("PATCH", f"/api/users/{admin_id}", user="admin",
                    json={"active": False}).status_code == 409
    assert api.call("PATCH", f"/api/users/{admin_id}", user="admin",
                    json={"role": "analyst"}).status_code == 409
    api.call("POST", "/api/users", user="admin", json={
        "username": "admin2", "password": "longenough", "role": "admin"})
    assert api.call("PATCH", f"/api/users/{admin_id}", user="admin",
                    json={"active": False}).status_code == 200


def test_user_changes_are_audited_without_passwords(api):
    api.call("POST", "/api/users", user="admin", json={
        "username": "ravi", "password": "ravi-pass-1", "role": "analyst"})
    rid = api.session.execute(text("SELECT id FROM users WHERE username = 'ravi'")).scalar()
    api.call("PATCH", f"/api/users/{rid}", user="admin", json={"role": "compliance"})
    rows = api.session.execute(text("SELECT action, actor, payload, deal_id FROM audit_entries "
                                    "WHERE action LIKE 'user_%' ORDER BY id")).all()
    assert [r[0] for r in rows] == ["user_created", "user_updated"]
    assert all(r[1] == "admin" and r[3] is None for r in rows)
    assert "ravi-pass" not in "".join(json.dumps(r[2]) for r in rows)
    assert rows[1][2]["changes"]["role"]["to"] == "compliance"


# ----------------------------------------------------------------- who may do what on a deal

def test_admin_has_no_deal_powers(api):
    deal = make_deal(api)
    assert api.call("POST", "/api/deals", user="admin", json={
        "external_id": "A-1", "name": "x", "transaction_class": "DEBT"}).status_code == 403
    for method, url, kw in [
        ("POST", f"/api/deals/{deal}/transition", {"json": {"to_stage": "QUALIFIED"}}),
        ("POST", f"/api/deals/{deal}/documents",
         {"files": {"file": ("x.pdf", b"x")}, "data": {"doc_class": "nda"}}),
        ("POST", "/api/parties", {"json": {"party_type": "company", "display_name": "x"}}),
        ("POST", f"/api/deals/{deal}/conditions", {"json": {"description": "x",
                                                            "cp_type": "y"}}),
        ("POST", f"/api/deals/{deal}/mandates", {"json": {"title": "m", "side": "raise"}}),
        ("POST", f"/api/deals/{deal}/signoffs", {"json": {"note": "ok"}}),
        ("PATCH", f"/api/deals/{deal}", {"json": {"regulatory_flags": ["SEBI"]}}),
        ("POST", f"/api/deals/{deal}/members", {"json": {"username": "asha"}}),
        ("POST", "/api/jobs", {"json": {"inputs": {"brief": "x"}, "deal_id": deal}}),
    ]:
        assert api.call(method, url, user="admin", **kw).status_code == 403, (method, url)


def test_only_a_dealmaker_moves_a_deal(api):
    deal = make_deal(api)
    api.add_member(deal, "asha")
    for user in ("asha", "priya", "admin"):
        assert move(api, deal, "WITHDRAWN", user=user, reason_code="x").status_code == 403, user
    link(api, deal, party(api)["id"], "advisor")
    assert move(api, deal, "QUALIFIED").status_code == 200
    assert api.call("GET", f"/api/deals/{deal}/guards", user="asha",
                    params={"to_stage": "MANDATED"}).status_code == 200  # preview is open


def test_an_analyst_does_the_deal_work_but_decides_nothing(api):
    deal = make_deal(api)
    api.add_member(deal, "asha")
    as_asha = {"user": "asha"}
    assert upload(api, deal, user="asha")
    p = party(api, user="asha")
    assert link(api, deal, p["id"], "buyer", user="asha")
    assert api.call("POST", f"/api/deals/{deal}/mandates", json={"title": "m", "side": "raise"},
                    **as_asha).status_code == 201
    cp = api.call("POST", f"/api/deals/{deal}/conditions", **as_asha,
                  json={"description": "x", "cp_type": "y"})
    assert cp.status_code == 201
    assert api.call("PATCH", f"/api/conditions/{cp.json()['id']}", **as_asha,
                    json={"status": "in_progress"}).status_code == 200
    assert submit(api, {"brief": "intro"}, deal_id=deal, user="asha")["created_by"] == "asha"
    run_worker(api)
    (h,) = api.call("GET", "/api/handoffs", **as_asha).json()
    assert api.call("POST", f"/api/handoffs/{h['id']}/resolve", json=DIRECTIVE,
                    **as_asha).status_code == 403
    assert api.call("POST", f"/api/deals/{deal}/signoffs", json={"note": "ok"},
                    **as_asha).status_code == 403
    assert api.call("POST", f"/api/deals/{deal}/members", json={"username": "admin"},
                    **as_asha).status_code == 403
    assert api.call("PATCH", f"/api/deals/{deal}", json={"regulatory_flags": ["SEBI"]},
                    **as_asha).status_code == 403


def test_compliance_reads_and_signs_off_but_does_not_edit_deal_data(api):
    deal = make_deal(api)
    as_priya = {"user": "priya"}
    assert api.call("GET", f"/api/deals/{deal}", **as_priya).status_code == 200
    assert api.call("POST", f"/api/deals/{deal}/documents", **as_priya,
                    files={"file": ("x.pdf", b"x")},
                    data={"doc_class": "nda"}).status_code == 403
    assert api.call("POST", "/api/jobs", **as_priya,
                    json={"inputs": {"brief": "x"}, "deal_id": deal}).status_code == 403
    assert api.call("POST", f"/api/deals/{deal}/signoffs", **as_priya,
                    json={"note": "cleared"}).status_code == 201
    assert api.call("PATCH", f"/api/deals/{deal}", **as_priya,
                    json={"regulatory_flags": ["SEBI"]}).status_code == 200


def test_every_role_check_runs_before_the_wall_check(api):
    """Role is checked first, so an off-wall analyst learns nothing about the deal."""
    deal = make_deal(api, "R-1")
    assert move(api, deal, "QUALIFIED", user="asha").status_code == 403
    set_stage(api, deal, "QUALIFIED")
    assert api.call("GET", f"/api/deals/{deal}", user="asha").status_code == 404