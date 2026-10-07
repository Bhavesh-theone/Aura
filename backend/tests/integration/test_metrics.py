"""Metrics (F1.5, I6, SM1-SM6) and the dashboard counts (X4)."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from aura.core.domain.deal import StageHistoryEntry
from aura.core.domain.enums import DealStage as S
from aura.core.services.metrics import stage_dwell
from aura.core.services.outbound import record_outbound_executed
from aura.data.repositories.sql import SqlAuditRepository
from aura.data.walls import SYSTEM
from tests.integration.helpers import (make_deal, move, party, link, run_worker, set_stage,
                                       submit, upload)
from tests.integration.test_guards import MOVES

T0 = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)


def _row(i, deal, frm, to, hours, regression=False):
    return StageHistoryEntry(id=i, deal_id=deal, from_stage=frm, to_stage=to,
                             entered_at=T0 + timedelta(hours=hours), actor="u",
                             reason_code=None, is_regression=regression)


def test_stage_dwell_comes_only_from_history_and_covers_ended_stays():
    history = [
        _row(1, 1, None, S.ORIGINATED, 0), _row(2, 1, S.ORIGINATED, S.QUALIFIED, 10),
        _row(3, 1, S.QUALIFIED, S.MANDATED, 40),
        _row(4, 2, None, S.ORIGINATED, 0), _row(5, 2, S.ORIGINATED, S.QUALIFIED, 20),
        _row(6, 3, None, S.ORIGINATED, 5),  # still in ORIGINATED: an open stay, not counted
    ]
    by_stage = {d.stage: d for d in stage_dwell(history)}
    assert by_stage["ORIGINATED"].n == 2
    assert by_stage["ORIGINATED"].median_hours == 15.0  # stays of 10h and 20h
    assert by_stage["ORIGINATED"].p90_hours == 20.0
    assert by_stage["QUALIFIED"].n == 1 and by_stage["QUALIFIED"].median_hours == 30.0
    assert "MANDATED" not in by_stage  # the deal is still there: no completed stay
    assert [d.stage for d in stage_dwell(history)] == ["ORIGINATED", "QUALIFIED"]


def test_p90_is_nearest_rank_over_many_stays():
    history = []
    for deal in range(1, 11):  # ten ORIGINATED stays of 1..10 hours
        history += [_row(deal * 2, deal, None, S.ORIGINATED, 0),
                    _row(deal * 2 + 1, deal, S.ORIGINATED, S.QUALIFIED, deal)]
    (originated,) = [d for d in stage_dwell(history) if d.stage == "ORIGINATED"]
    assert originated.n == 10 and originated.median_hours == 5.5
    assert originated.p90_hours == 9.0


def test_regressions_extend_the_stage_they_left_and_count_as_another_stay():
    history = [_row(1, 1, None, S.ORIGINATED, 0),
               _row(2, 1, S.ORIGINATED, S.QUALIFIED, 1),
               _row(3, 1, S.QUALIFIED, S.ORIGINATED, 3, regression=True),
               _row(4, 1, S.ORIGINATED, S.QUALIFIED, 7)]
    by_stage = {d.stage: d for d in stage_dwell(history)}
    assert by_stage["ORIGINATED"].n == 2 and by_stage["QUALIFIED"].n == 1


def _close_a_deal(api, external_id="M-1"):
    d = make_deal(api, external_id)
    for to, names, satisfy, _ in MOVES:
        satisfy(api, d)
        assert move(api, d, to).status_code == 200, to
    return d


def test_metrics_payload_for_a_deal_closed_end_to_end(api):
    d = _close_a_deal(api)
    submit(api, {"brief": "x"}, deal_id=d)
    run_worker(api)
    m = api.call("GET", "/api/metrics").json()
    assert set(m) == {"stage_dwell", "success", "reliability"}  # reliability: added in 0011
    assert m["reliability"] == {"dead_lettered_segments": 0, "retried_segments": 0,
                                "recovered_segments": 0, "fallback_runs": 0,
                                "budget_deferrals": 0}

    assert set(m["success"]) == {"guarded_forward_transitions_pct", "runs_traceable_pct",
                                 "audit_chain_ok", "handoff_rejections_422",
                                 "outbound_executed", "deals_closed_end_to_end"}
    assert m["success"] == {"guarded_forward_transitions_pct": 100.0,
                            "runs_traceable_pct": 100.0, "audit_chain_ok": True,
                            "handoff_rejections_422": 0, "outbound_executed": 0,
                            "deals_closed_end_to_end": 1}
    stays = {s["stage"]: s for s in m["stage_dwell"]}
    assert set(stays) == {"ORIGINATED", "QUALIFIED", "MANDATED", "PREPARED", "MARKETED",
                          "MATCHED", "BID_AUCTION", "NEGOTIATION", "DILIGENCE",
                          "DOCUMENTATION", "CONDITIONS_PRECEDENT"}  # CLOSED has no end
    assert all(set(s) == {"stage", "n", "median_hours", "p90_hours"} and s["n"] == 1
               and s["median_hours"] >= 0 for s in stays.values())


def test_guarded_percentage_drops_when_a_forward_move_has_no_guard_rows(api):
    d = make_deal(api)
    link(api, d, party(api)["id"], "advisor")
    assert move(api, d, "QUALIFIED").status_code == 200
    assert api.call("GET", "/api/metrics").json()["success"][
        "guarded_forward_transitions_pct"] == 100.0
    # a history row with no evaluations behind it (e.g. written outside the service)
    api.session.execute(text(
        "INSERT INTO deal_stage_history (deal_id, from_stage, to_stage, entered_at, actor, "
        "is_regression) VALUES (:d, 'QUALIFIED', 'MANDATED', '2026-10-06 12:00:00', 'x', 0)"),
        {"d": d})
    api.session.commit()
    assert api.call("GET", "/api/metrics").json()["success"][
        "guarded_forward_transitions_pct"] == 50.0


def test_regressions_and_exits_are_outside_sm1(api):
    d = make_deal(api)
    set_stage(api, d, "MATCHED")
    assert move(api, d, "MARKETED", reason_code="buyer_dropped").status_code == 200
    assert move(api, d, "WITHDRAWN", reason_code="client_pulled").status_code == 200
    s = api.call("GET", "/api/metrics").json()["success"]
    assert s["guarded_forward_transitions_pct"] == 100.0  # no forward move to be unguarded
    assert s["deals_closed_end_to_end"] == 0


def test_a_deal_forced_to_closed_without_its_guards_is_not_closed_end_to_end(api):
    d = make_deal(api)
    set_stage(api, d, "CONDITIONS_PRECEDENT")
    api.call("POST", f"/api/deals/{d}/conditions", json={"description": "x", "cp_type": "y"})
    cp = api.session.execute(text("SELECT id FROM condition_precedent")).scalar()
    api.call("PATCH", f"/api/conditions/{cp}", json={"status": "satisfied"})
    assert move(api, d, "CLOSED").status_code == 200
    assert api.call("GET", "/api/metrics").json()["success"]["deals_closed_end_to_end"] == 0


def test_metrics_are_wall_filtered(api):
    _close_a_deal(api)
    mine = api.call("GET", "/api/metrics").json()
    theirs = api.call("GET", "/api/metrics", user="asha").json()
    assert mine["success"]["deals_closed_end_to_end"] == 1 and mine["stage_dwell"]
    assert theirs["stage_dwell"] == []
    assert theirs["success"]["deals_closed_end_to_end"] == 0
    assert theirs["success"]["guarded_forward_transitions_pct"] == 100.0
    assert api.client.get("/api/metrics").status_code == 401


def test_untraceable_runs_lower_the_traceability_percentage(api):
    d = make_deal(api)
    submit(api, {"brief": "x"}, deal_id=d)
    run_worker(api)
    assert api.call("GET", "/api/metrics").json()["success"]["runs_traceable_pct"] == 100.0
    api.session.execute(text("UPDATE agent_run SET prompt_hash = 'tampered'"))
    api.session.commit()
    assert api.call("GET", "/api/metrics").json()["success"]["runs_traceable_pct"] == 0.0


def test_handoff_rejections_and_outbound_executions_are_counted_from_the_audit(api):
    d = make_deal(api)
    api.call("POST", "/api/handoffs", json={"task_type": "x", "deal_id": d,
                                            "context_package": {}})
    s = api.call("GET", "/api/metrics").json()["success"]
    assert s["handoff_rejections_422"] == 1 and s["outbound_executed"] == 0
    assert api.call("GET", "/api/metrics", user="asha").json()["success"][
        "handoff_rejections_422"] == 0  # a wall hides the rejection from asha

    # were an outbound action ever executed, the recorder puts it on the chain and SM5 sees it
    record_outbound_executed("send_email", {"to": "x", "body": "y"}, "system", d, None,
                             SqlAuditRepository(api.session, SYSTEM))
    api.session.commit()
    assert api.call("GET", "/api/metrics").json()["success"]["outbound_executed"] == 1
    assert api.call("GET", "/api/audit/verify").json()["ok"] is True


def test_no_email_flow_ever_executes_an_outbound_action(api):
    d = make_deal(api)
    submit(api, {"brief": "send the intro"}, deal_id=d)
    run_worker(api)
    (h,) = api.call("GET", "/api/handoffs").json()
    from tests.integration.helpers import DIRECTIVE
    api.call("POST", f"/api/handoffs/{h['id']}/resolve", json=DIRECTIVE)
    run_worker(api)
    assert api.call("GET", "/api/metrics").json()["success"]["outbound_executed"] == 0
    assert api.session.execute(text("SELECT COUNT(*) FROM audit_entries WHERE action = "
                                    "'outbound_executed'")).scalar() == 0


def test_dashboard_counts_closed_and_ended_deals_by_stage(api):
    _close_a_deal(api, "M-1")
    ended = make_deal(api, "M-2")
    assert move(api, ended, "WITHDRAWN", reason_code="client_pulled").status_code == 200
    make_deal(api, "M-3")
    s = api.call("GET", "/api/dashboard/summary").json()
    assert s["open_deals"] == 1 and s["closed_deals"] == 1 and s["ended_deals"] == 1
    assert s["deals_by_stage"] == {"CLOSED": 1, "WITHDRAWN": 1, "ORIGINATED": 1}
    assert sum(s["deals_by_stage"].values()) == 3
    assert s["deals_by_class"] == {"DEBT": 1}  # open deals only, as before