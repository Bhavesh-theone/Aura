import copy

import pytest
from sqlalchemy import text

from tests.integration.helpers import DIRECTIVE, make_deal, run_worker, submit

PACKAGE = {
    "what_happened": ["Agent noticed the engagement letter is unsigned"],
    "evidence": [{"type": "document", "id": 1}],
    "decision_required": {
        "question": "Should we chase the client for the signed engagement letter?",
        "options": [
            {"id": "chase", "label": "Chase now", "consequence": "Client gets a reminder today.",
             "reversible": False},
            {"id": "wait", "label": "Wait a week", "consequence": "No contact until next week.",
             "reversible": True}],
        "recommendation": "chase", "confidence": 0.7},
    "if_you_do_nothing": {
        "consequence": "The deal stays at QUALIFIED and the mandate is not started.",
        "auto_escalate_at": "2030-01-01T00:00:00+00:00", "escalates_to_role": "dealmaker"},
}


def _post(api, package, user="bhavesh", **extra):
    body = {"task_type": "chase_client", "context_package": package, **extra}
    return api.call("POST", "/api/handoffs", user=user, json=body)


def test_post_valid_handoff_creates_task_and_handoff(api):
    deal = make_deal(api)
    r = _post(api, PACKAGE, deal_id=deal, materiality_inr=1000)
    assert r.status_code == 201, r.text
    h = r.json()
    assert h["status"] == "open" and h["direction"] == "bot_to_human"
    assert h["trigger"] == "explicit_request" and h["deal_id"] == deal
    assert h["auto_escalate_at"].startswith("2030-01-01")
    assert h["context_package"]["decision_required"]["recommendation"] == "chase"
    task = api.session.execute(text("SELECT task_type, assignment_mode, status, materiality_inr "
                                    "FROM task WHERE id = :i"), {"i": h["task_id"]}).one()
    assert tuple(task) == ("chase_client", "bot_supervised", "review", 1000)
    actions = [a for (a,) in api.session.execute(text("SELECT action FROM audit_entries"))]
    assert "handoff_created" in actions


def _without(path):
    pkg = copy.deepcopy(PACKAGE)
    node = pkg
    for key in path[:-1]:
        node = node[key]
    del node[path[-1]]
    return pkg


def _with(path, value):
    pkg = copy.deepcopy(PACKAGE)
    node = pkg
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    return pkg


@pytest.mark.parametrize("package", [
    _without(["if_you_do_nothing"]),
    _without(["decision_required"]),
    _without(["what_happened"]),
    _without(["evidence"]),
    _with(["decision_required", "question"], "Too short?"),
    _with(["decision_required", "options"], PACKAGE["decision_required"]["options"][:1]),
    _with(["decision_required", "options"],
          [{"id": str(i), "label": "x", "consequence": "y", "reversible": True}
           for i in range(6)]),
    _with(["decision_required", "recommendation"], "something-else"),
    _with(["decision_required", "confidence"], 2),
    _with(["if_you_do_nothing", "consequence"], "Nothing happens."),
    _without(["if_you_do_nothing", "auto_escalate_at"]),
    _without(["if_you_do_nothing", "escalates_to_role"]),
])
def test_bot_to_human_handoff_missing_required_parts_is_422(api, package):
    r = _post(api, package)
    assert r.status_code == 422, r.text
    assert api.session.execute(text("SELECT COUNT(*) FROM handoff")).scalar() == 0
    assert api.session.execute(text("SELECT COUNT(*) FROM task")).scalar() == 0


def test_human_to_bot_handoff_needs_a_directive_with_do_not_revisit(api):
    kw = dict(direction="human_to_bot", trigger="human_correction")
    assert _post(api, {"note": "redo it"}, **kw).status_code == 422
    bad = copy.deepcopy(DIRECTIVE)
    del bad["new_constraints"]["do_not_revisit"]
    assert _post(api, {"note": "redo it"}, directive=bad, **kw).status_code == 422
    ok = _post(api, {"note": "redo it"}, directive=DIRECTIVE, **kw)
    assert ok.status_code == 201 and ok.json()["directive"]["decision"] == "approve"


def _gated_handoff(api, deal_id=None):
    """Submit a job, let the stub worker run it, return the open handoff it raised."""
    job = submit(api, {"brief": "intro to Ravi"}, deal_id=deal_id)
    assert run_worker(api) == 1
    (h,) = api.call("GET", "/api/handoffs", params={"status": "open"}).json()
    return job, h


def test_gated_job_raises_a_valid_handoff_instead_of_an_approval(api):
    deal = make_deal(api)
    job, h = _gated_handoff(api, deal)
    assert h["trigger"] == "policy_required" and h["deal_id"] == deal and h["job_id"] == job["id"]
    assert h["task_type"] == "send_email" and h["status"] == "open"
    decision = h["context_package"]["decision_required"]
    assert [o["id"] for o in decision["options"]] == ["approve", "reject"]
    assert decision["recommendation"] == "approve"
    assert h["context_package"]["if_you_do_nothing"]["consequence"].startswith(
        "Job stays paused; escalates to dealmaker at ")
    assert api.call("GET", f"/api/jobs/{job['id']}").json()["status"] == "awaiting_approval"
    assert api.session.execute(text("SELECT COUNT(*) FROM audit_entries WHERE "
                                    "action = 'handoff_created'")).scalar() == 1


def test_list_and_get_handoffs(api):
    _, h = _gated_handoff(api)
    assert api.call("GET", "/api/handoffs", params={"status": "resolved"}).json() == []
    assert [x["id"] for x in api.call("GET", "/api/handoffs").json()] == [h["id"]]
    one = api.call("GET", f"/api/handoffs/{h['id']}").json()
    assert one == h
    assert {"id", "deal_id", "task_id", "trigger", "context_package", "status", "created_at",
            "auto_escalate_at"} <= set(one)
    assert api.call("GET", "/api/handoffs/999").status_code == 404
    assert api.call("GET", "/api/handoffs", params={"status": "bogus"}).status_code == 422


@pytest.mark.parametrize("user", ["asha", "admin"])
def test_analyst_and_admin_cannot_resolve(api, user):
    _, h = _gated_handoff(api)
    r = api.call("POST", f"/api/handoffs/{h['id']}/resolve", user=user, json=DIRECTIVE)
    assert r.status_code == 403
    assert api.call("GET", f"/api/handoffs/{h['id']}").json()["status"] == "open"


def test_compliance_resolves_policy_required_handoffs_only(api):
    deal = make_deal(api)
    _, h = _gated_handoff(api, deal)
    assert h["trigger"] == "policy_required"
    ok = api.call("POST", f"/api/handoffs/{h['id']}/resolve", user="priya", json=DIRECTIVE)
    assert ok.status_code == 200 and ok.json()["resolved_by"] == "priya"

    other = _post(api, PACKAGE, deal_id=deal, trigger="materiality_gate").json()
    chase = {**DIRECTIVE, "decision": "chase"}
    assert api.call("POST", f"/api/handoffs/{other['id']}/resolve", user="priya",
                    json=chase).status_code == 403
    assert api.call("POST", f"/api/handoffs/{other['id']}/resolve",
                    json=chase).status_code == 200


def test_approve_continues_the_job_via_the_stub(api):
    job, h = _gated_handoff(api)
    r = api.call("POST", f"/api/handoffs/{h['id']}/resolve", json=DIRECTIVE)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "resolved" and r.json()["resolved_by"] == "bhavesh"
    assert r.json()["directive"]["decision"] == "approve"
    assert api.call("GET", f"/api/jobs/{job['id']}").json()["status"] == "pending"

    assert run_worker(api) == 1  # the queued next segment
    done = api.call("GET", f"/api/jobs/{job['id']}").json()
    assert done["status"] == "complete" and done["result"]["sent"] is True
    assert api.call("GET", "/api/handoffs", params={"status": "open"}).json() == []
    assert len(api.call("GET", "/api/handoffs", params={"status": "resolved"}).json()) == 1


def test_reject_ends_the_job(api):
    job, h = _gated_handoff(api)
    r = api.call("POST", f"/api/handoffs/{h['id']}/resolve",
                 json={**DIRECTIVE, "decision": "reject"})
    assert r.status_code == 200
    assert api.call("GET", f"/api/jobs/{job['id']}").json()["status"] == "rejected"
    assert run_worker(api) == 0


def test_resolving_twice_is_409(api):
    _, h = _gated_handoff(api)
    assert api.call("POST", f"/api/handoffs/{h['id']}/resolve", json=DIRECTIVE).status_code == 200
    assert api.call("POST", f"/api/handoffs/{h['id']}/resolve", json=DIRECTIVE).status_code == 409


@pytest.mark.parametrize("directive", [
    {k: v for k, v in DIRECTIVE.items() if k != "decision"},
    {**DIRECTIVE, "reasoning": "short"},
    {k: v for k, v in DIRECTIVE.items() if k != "new_constraints"},
    {**DIRECTIVE, "new_constraints": {}},
    {k: v for k, v in DIRECTIVE.items() if k != "next_checkpoint"},
    {**DIRECTIVE, "next_checkpoint": {"condition": "only half"}},
    {**DIRECTIVE, "decision": "not-an-option"},
])
def test_resolve_directive_is_validated(api, directive):
    _, h = _gated_handoff(api)
    r = api.call("POST", f"/api/handoffs/{h['id']}/resolve", json=directive)
    assert r.status_code == 422, r.text
    assert api.call("GET", f"/api/handoffs/{h['id']}").json()["status"] == "open"


def test_resolve_accepts_a_directive_wrapper_and_unknown_handoff_is_404(api):
    _, h = _gated_handoff(api)
    assert api.call("POST", f"/api/handoffs/{h['id']}/resolve",
                    json={"directive": DIRECTIVE}).status_code == 200
    assert api.call("POST", "/api/handoffs/999/resolve", json=DIRECTIVE).status_code == 404


def test_create_and_resolve_are_audited(api):
    _, h = _gated_handoff(api)
    api.call("POST", f"/api/handoffs/{h['id']}/resolve", json=DIRECTIVE)
    rows = api.session.execute(text("SELECT action, actor, payload FROM audit_entries "
                                    "WHERE action LIKE 'handoff_%' ORDER BY id")).all()
    assert [r[0] for r in rows] == ["handoff_created", "handoff_resolved"]
    assert rows[1][1] == "bhavesh" and rows[1][2]["decision"] == "approve"


def test_materiality_above_the_cap_gates_and_is_flagged(api):
    """A proposal worth more than 5 crore is draft-only, whatever its category."""
    from aura.core.domain.enums import ActionCategory
    from aura.core.domain.segment import ProposedAction
    from aura.core.ports.orchestrator import OrchestratorResult

    class BigNote:
        def run(self, context_in, run_context):
            return OrchestratorResult(False, {"x": 1}, ProposedAction(
                tool="add_internal_note", category=ActionCategory.INTERNAL_WRITE,
                arguments={"amount_inr": 75_000_000}, summary="Note a 7.5 crore payment",
                materiality_inr=75_000_000))

    submit(api, {"brief": "x"})
    assert run_worker(api, BigNote()) == 1
    (h,) = api.call("GET", "/api/handoffs", params={"status": "open"}).json()
    assert h["trigger"] == "materiality_gate"
    assert h["context_package"]["decision_required"]["recommendation"] == "reject"
    assert api.session.execute(text("SELECT materiality_inr FROM task")).scalar() == 75_000_000


def test_overdue_open_handoffs_escalate_but_stay_open_for_humans(api):
    from datetime import datetime, timedelta, timezone

    from aura.worker.runner import sweep_escalations
    from tests.integration.helpers import NullEvents
    _, h = _gated_handoff(api)
    assert sweep_escalations(api.session, NullEvents()) == 0
    api.session.execute(text("UPDATE handoff SET auto_escalate_at = :t"),
                        {"t": datetime.now(timezone.utc) - timedelta(hours=1)})
    api.session.commit()
    assert sweep_escalations(api.session, NullEvents()) == 1
    (still,) = api.call("GET", "/api/handoffs", params={"status": "open"}).json()
    assert still["id"] == h["id"] and still["status"] == "escalated"
    assert api.call("POST", f"/api/handoffs/{h['id']}/resolve", json=DIRECTIVE).status_code == 200
