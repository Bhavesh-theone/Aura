"""Deal walls (PRD F10): membership is enforced in the repositories, admins included."""
import pytest
from sqlalchemy import text

from tests.integration.helpers import DIRECTIVE, make_deal, run_worker, submit, upload


@pytest.fixture()
def walled(api):
    """A deal only bhavesh is on, with a document, a job awaiting a decision and a run."""
    deal = make_deal(api, "W-1")
    doc = upload(api, deal, "ts.pdf", "nda")
    job = submit(api, {"brief": "intro"}, deal_id=deal)
    run_worker(api)
    return {"deal": deal, "doc": doc["id"], "job": job["id"]}


def test_creating_a_deal_creates_its_wall_with_the_creator_and_compliance_as_members(api):
    deal = make_deal(api, "W-9", user="asha")
    rows = api.session.execute(text(
        "SELECT w.deal_id, u.username, m.removed_at FROM wall w "
        "JOIN wall_member m ON m.wall_id = w.id JOIN users u ON u.id = m.user_id "
        "ORDER BY m.id")).all()
    # compliance joins so that it can manage the wall it would otherwise not be able to reach
    assert [tuple(r) for r in rows] == [(deal, "asha", None), (deal, "priya", None)]
    members = api.call("GET", f"/api/deals/{deal}/members", user="asha").json()
    assert [m["username"] for m in members] == ["asha", "priya"]
    assert api.call("GET", f"/api/deals/{deal}", user="priya").status_code == 200
    assert api.call("GET", f"/api/deals/{deal}", user="bhavesh").status_code == 404


def test_non_member_gets_404_on_every_deal_scoped_route(api, walled):
    d, doc, job = walled["deal"], walled["doc"], walled["job"]
    asha = dict(user="asha")
    assert api.call("GET", "/api/deals", **asha).json() == []
    for method, url, kw in [
        ("GET", f"/api/deals/{d}", {}),
        ("GET", f"/api/deals/{d}/guards?to_stage=QUALIFIED", {}),
        ("GET", f"/api/deals/{d}/documents", {}),
        ("POST", f"/api/deals/{d}/documents",
         {"files": {"file": ("x.pdf", b"x")}, "data": {"doc_class": "nda"}}),
        ("GET", f"/api/documents/{doc}/download", {}),
        ("GET", f"/api/deals/{d}/diligence", {}),
        ("GET", f"/api/deals/{d}/conditions", {}),
        ("POST", f"/api/deals/{d}/conditions", {"json": {"description": "x", "cp_type": "y"}}),
        ("GET", f"/api/deals/{d}/mandates", {}),
        ("POST", f"/api/deals/{d}/mandates", {"json": {"title": "m", "side": "raise"}}),
        ("GET", f"/api/deals/{d}/members", {}),
        ("GET", f"/api/agent-runs?deal_id={d}", {}),
        ("GET", f"/api/jobs/{job}", {}),
    ]:
        r = api.call(method, url, **asha, **kw)
        assert r.status_code == 404, (method, url, r.status_code)

    party = api.call("POST", "/api/parties", json={"party_type": "company",
                                                   "display_name": "Acme"}).json()
    assert api.call("POST", f"/api/deals/{d}/parties", user="asha",
                    json={"party_id": party["id"], "role": "buyer"}).status_code == 404


def test_a_dealmaker_off_the_wall_cannot_move_the_deal(api):
    deal = make_deal(api, "W-T", user="asha")  # bhavesh, the only dealmaker, is not on it
    assert api.call("POST", f"/api/deals/{deal}/transition",
                    json={"to_stage": "QUALIFIED"}).status_code == 404
    assert api.call("PATCH", f"/api/deals/{deal}",
                    json={"regulatory_flags": ["SEBI"]}).status_code == 404


def test_document_download_and_access_log_are_walled(api, walled):
    doc = walled["doc"]
    assert api.call("GET", f"/api/documents/{doc}/download", user="asha").status_code == 404
    assert api.session.execute(text("SELECT COUNT(*) FROM doc_access_log")).scalar() == 0
    assert api.call("GET", f"/api/documents/{doc}/download").status_code == 200


def test_diligence_and_conditions_by_item_id_are_walled(api, walled):
    d = walled["deal"]
    cp = api.call("POST", f"/api/deals/{d}/conditions",
                  json={"description": "RBI nod", "cp_type": "regulatory"}).json()
    assert api.call("PATCH", f"/api/conditions/{cp['id']}", user="asha",
                    json={"status": "satisfied"}).status_code == 404
    api.session.execute(text("INSERT INTO diligence_item (deal_id, prompt, severity, status, "
                             "evidence_doc_ids) VALUES (:d, 'p', 'standard', 'open', '[]')"),
                        {"d": d})
    api.session.commit()
    item_id = api.session.execute(text("SELECT id FROM diligence_item")).scalar()
    assert api.call("PATCH", f"/api/diligence/{item_id}", user="asha",
                    json={"status": "waived", "waiver_justification": "x"}).status_code == 404


def test_handoffs_agent_runs_jobs_and_activity_are_filtered(api, walled):
    assert len(api.call("GET", "/api/handoffs").json()) == 1
    assert api.call("GET", "/api/handoffs", user="asha").json() == []
    (h,) = api.call("GET", "/api/handoffs").json()
    assert api.call("GET", f"/api/handoffs/{h['id']}", user="asha").status_code == 404

    assert len(api.call("GET", "/api/agent-runs").json()) == 1
    assert api.call("GET", "/api/agent-runs", user="asha").json() == []
    assert api.call("GET", "/api/jobs", user="asha").json() == []
    assert len(api.call("GET", "/api/jobs").json()) == 1

    mine = {e["deal_id"] for e in api.call("GET", "/api/activity").json()}
    assert walled["deal"] in mine
    assert all(e["deal_id"] != walled["deal"] for e in api.call(
        "GET", "/api/activity", user="asha").json())


def test_a_non_member_cannot_attach_a_job_to_the_deal(api, walled):
    r = api.call("POST", "/api/jobs", user="asha",
                 json={"inputs": {"brief": "x"}, "deal_id": walled["deal"]})
    assert r.status_code == 404


def test_no_role_is_exempt_from_a_wall(api):
    deal = make_deal(api, "W-A", user="asha")  # bhavesh (dealmaker) is not on this wall
    assert api.call("GET", f"/api/deals/{deal}").status_code == 404
    assert api.call("GET", "/api/deals").json() == []
    # the compliance officer who manages walls is bound by them too, once she steps off
    assert api.call("DELETE", f"/api/deals/{deal}/members", user="priya",
                    json={"username": "priya"}).status_code == 200
    assert api.call("GET", f"/api/deals/{deal}", user="priya").status_code == 404
    assert api.call("POST", f"/api/deals/{deal}/members", user="priya",
                    json={"username": "bhavesh"}).status_code == 404

    job = submit(api, {"brief": "x"}, deal_id=deal, user="asha")
    run_worker(api)
    (h,) = api.call("GET", "/api/handoffs", user="asha").json()
    assert api.call("GET", "/api/handoffs").json() == []
    assert api.call("POST", f"/api/handoffs/{h['id']}/resolve",
                    json=DIRECTIVE).status_code == 404
    assert api.call("GET", f"/api/jobs/{job['id']}").status_code == 404


def test_compliance_manages_membership_and_it_takes_effect_immediately(api, walled):
    d = walled["deal"]
    assert api.call("GET", f"/api/deals/{d}", user="asha").status_code == 404
    api.add_member(d, "asha")
    assert api.call("GET", f"/api/deals/{d}", user="asha").status_code == 200
    assert len(api.call("GET", "/api/handoffs", user="asha").json()) == 1
    assert api.call("GET", f"/api/documents/{walled['doc']}/download",
                    user="asha").status_code == 200
    members = api.call("GET", f"/api/deals/{d}/members").json()
    assert [m["username"] for m in members] == ["bhavesh", "priya", "asha"]

    r = api.call("DELETE", f"/api/deals/{d}/members", user="priya",
                 json={"username": "asha"})
    assert r.status_code == 200 and [m["username"] for m in r.json()] == ["bhavesh", "priya"]
    assert api.call("GET", f"/api/deals/{d}", user="asha").status_code == 404
    assert api.session.execute(text(
        "SELECT removed_at IS NOT NULL FROM wall_member ORDER BY id")).scalars().all() == [
        0, 0, 1]

    api.add_member(d, "asha")  # re-adding after removal works
    assert api.call("GET", f"/api/deals/{d}", user="asha").status_code == 200


def test_membership_changes_are_audited_and_validated(api, walled):
    d = walled["deal"]
    api.add_member(d, "asha")
    for body, status in [({"username": "asha"}, 409), ({"username": "nobody"}, 404)]:
        assert api.call("POST", f"/api/deals/{d}/members", user="priya",
                        json=body).status_code == status
    assert api.call("DELETE", f"/api/deals/{d}/members", user="priya",
                    json={"username": "nobody"}).status_code == 404
    api.call("DELETE", f"/api/deals/{d}/members", user="priya", json={"username": "asha"})
    rows = api.session.execute(text("SELECT action, actor, payload, deal_id FROM audit_entries "
                                    "WHERE action LIKE 'wall_member_%' AND actor = 'priya' "
                                    "ORDER BY id")).all()
    assert [r[0] for r in rows] == ["wall_member_added", "wall_member_removed"]
    assert rows[0][2]["username"] == "asha" and rows[0][3] == d


@pytest.mark.parametrize("user", ["asha", "bhavesh", "admin"])
def test_only_compliance_manages_membership(api, user):
    deal = make_deal(api, "W-M", user="asha")
    api.add_member(deal, "bhavesh")
    r = api.call("POST", f"/api/deals/{deal}/members", user=user, json={"username": "admin"})
    assert r.status_code == 403
    assert api.call("DELETE", f"/api/deals/{deal}/members", user=user,
                    json={"username": "asha"}).status_code == 403


def test_dashboard_only_counts_walled_in_deals(api, walled):
    mine = api.call("GET", "/api/dashboard/summary").json()
    theirs = api.call("GET", "/api/dashboard/summary", user="asha").json()
    assert mine["open_deals"] == 1 and mine["decisions_waiting"] == 1
    assert theirs["open_deals"] == 0 and theirs["decisions_waiting"] == 0
    assert theirs["deals_by_stage"] == {} and theirs["deals_by_class"] == {}
    assert all(e["deal_id"] is None for e in theirs["recent_activity"])
