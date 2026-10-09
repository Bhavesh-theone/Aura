"""do_not_revisit (F7.3b): a decision a person said not to revisit is not asked again."""
from sqlalchemy import text

from tests.integration.helpers import DIRECTIVE, make_deal, run_worker, submit


def _directive(do_not_revisit, decision="approve"):
    return {**DIRECTIVE, "decision": decision,
            "new_constraints": {"do_not_revisit": do_not_revisit}}


def _pause_and_resolve(api, deal, directive):
    job = submit(api, {"brief": "intro to Ravi"}, deal_id=deal)
    run_worker(api, limit=1)
    (h,) = [x for x in api.call("GET", "/api/handoffs", params={"status": "open"}).json()
            if x["job_id"] == job["id"]]
    r = api.call("POST", f"/api/handoffs/{h['id']}/resolve", json=directive)
    assert r.status_code == 200, r.text
    return job, h


def test_a_later_email_proposal_on_the_deal_is_skipped_and_the_earlier_approval_applies(api):
    deal = make_deal(api)
    _pause_and_resolve(api, deal, _directive(["send_email"]))
    run_worker(api)  # lets the first job finish
    handoffs_before = len(api.call("GET", "/api/handoffs").json())

    job = submit(api, {"brief": "another email"}, deal_id=deal)
    run_worker(api, limit=1)
    assert len(api.call("GET", "/api/handoffs").json()) == handoffs_before  # none created
    skipped = api.session.execute(text(
        "SELECT payload, deal_id, job_id, actor FROM audit_entries WHERE action = "
        "'handoff_skipped_per_directive'")).all()
    assert len(skipped) == 1
    assert skipped[0][1] == deal and skipped[0][2] == job["id"] and skipped[0][3] == "system"
    assert skipped[0][0]["approved"] is True and skipped[0][0]["task_type"] == "send_email"
    # the earlier approval carries the job on: a new segment is queued, then it completes
    assert api.call("GET", f"/api/jobs/{job['id']}").json()["status"] == "pending"
    run_worker(api)
    assert api.call("GET", f"/api/jobs/{job['id']}").json()["status"] == "complete"
    assert api.call("GET", "/api/audit/verify").json()["ok"] is True


def test_an_earlier_rejection_is_applied_too(api):
    deal = make_deal(api)
    _pause_and_resolve(api, deal, _directive(["send_email"], decision="reject"))
    job = submit(api, {"brief": "another email"}, deal_id=deal)
    run_worker(api, limit=1)
    assert api.call("GET", f"/api/jobs/{job['id']}").json()["status"] == "rejected"
    assert api.session.execute(text("SELECT COUNT(*) FROM audit_entries WHERE action = "
                                    "'handoff_skipped_per_directive'")).scalar() == 1


def test_without_the_constraint_every_proposal_still_gets_its_handoff(api):
    deal = make_deal(api)
    _pause_and_resolve(api, deal, _directive([]))
    submit(api, {"brief": "another email"}, deal_id=deal)
    run_worker(api)
    open_ = api.call("GET", "/api/handoffs", params={"status": "open"}).json()
    assert len(open_) == 1
    assert api.session.execute(text("SELECT COUNT(*) FROM audit_entries WHERE action = "
                                    "'handoff_skipped_per_directive'")).scalar() == 0


def test_the_constraint_only_binds_the_deal_it_was_given_on(api):
    deal, other = make_deal(api), make_deal(api, "H-2")
    _pause_and_resolve(api, deal, _directive(["send_email"]))
    submit(api, {"brief": "an email on another deal"}, deal_id=other)
    run_worker(api)
    open_ = [h for h in api.call("GET", "/api/handoffs", params={"status": "open"}).json()
             if h["deal_id"] == other]
    assert len(open_) == 1