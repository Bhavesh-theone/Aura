"""One guard set per forward move (PRD F2, GL1): each blocks until satisfied from held data."""
import itertools

import pytest
from sqlalchemy import text

from tests.integration.helpers import (link, make_deal, mark_executed, move, party, set_stage,
                                       upload, upload_executed)

FORWARD = ["ORIGINATED", "QUALIFIED", "MANDATED", "PREPARED", "MARKETED", "MATCHED",
           "BID_AUCTION", "NEGOTIATION", "DILIGENCE", "DOCUMENTATION",
           "CONDITIONS_PRECEDENT", "CLOSED"]
HARD = {"title": "Mandate", "side": "raise", "criteria": [
    {"criterion_key": "ticket_size_inr", "operator": "gte", "value": 100,
     "hardness": "hard"}]}


def _guards(api, deal, to):
    r = api.call("GET", f"/api/deals/{deal}/guards", params={"to_stage": to})
    assert r.status_code == 200
    return {g["guard_name"]: g for g in r.json()}


def _clear_blockers(api, deal):
    """Satisfy every blocker on the checklist (created on entering DILIGENCE)."""
    evidence = upload(api, deal, "evidence.pdf", "financial_statement")["id"]
    for item in api.call("GET", f"/api/deals/{deal}/diligence").json():
        if item["severity"] == "blocker":
            r = api.call("PATCH", f"/api/diligence/{item['id']}",
                         json={"status": "satisfied", "evidence_doc_ids": [evidence]})
            assert r.status_code == 200


def _cp(api, deal, status=None):
    cp = api.call("POST", f"/api/deals/{deal}/conditions",
                  json={"description": "RBI nod", "cp_type": "regulatory"}).json()
    if status:
        r = api.call("PATCH", f"/api/conditions/{cp['id']}", json={"status": status})
        assert r.status_code == 200
    return cp


def _t1(api, d):
    link(api, d, party(api)["id"], "advisor")


def _t2(api, d):
    upload_executed(api, d, "el.pdf", "engagement_letter")


def _t3(api, d):
    assert api.call("POST", f"/api/deals/{d}/mandates", json=HARD).status_code == 201


def _t4(api, d):
    upload(api, d, "fs.pdf", "financial_statement")


def _t5(api, d):
    link(api, d, party(api)["id"], "buyer")
    upload_executed(api, d, "nda.pdf", "nda")


def _t6(api, d):
    link(api, d, party(api)["id"], "buyer")
    link(api, d, party(api)["id"], "investor")


def _t7(api, d):
    upload(api, d, "val.pdf", "valuation_report")


def _t8(api, d):
    upload_executed(api, d, "ts.pdf", "term_sheet")


def _t9(api, d):
    _clear_blockers(api, d)


def _t10(api, d):
    upload_executed(api, d, "spa.pdf", "spa")


def _t11(api, d):
    _cp(api, d, "satisfied")


# (move to, its guards, what satisfies them, the role named to override them)
MOVES = [
    ("QUALIFIED", ["T1_party_with_identifier"], _t1, "dealmaker"),
    ("MANDATED", ["T2_engagement_letter"], _t2, "dealmaker"),
    ("PREPARED", ["T3_hard_criterion"], _t3, "dealmaker"),
    ("MARKETED", ["T4_financial_statement"], _t4, "dealmaker"),
    ("MATCHED", ["T5_counterparty_and_nda"], _t5, "dealmaker"),
    ("BID_AUCTION", ["T6_two_counterparties"], _t6, "dealmaker"),
    ("NEGOTIATION", ["T7_valuation_report"], _t7, "dealmaker"),
    ("DILIGENCE", ["T8_term_sheet"], _t8, "dealmaker"),
    ("DOCUMENTATION", ["T9_no_open_blockers", "T9_compliance_signoff"], _t9, "compliance"),
    ("CONDITIONS_PRECEDENT", ["T10_definitive_agreement"], _t10, "dealmaker"),
    ("CLOSED", ["T11_all_cps_cleared"], _t11, "compliance"),
]


def _prepare(api, deal, to):
    """Stand the deal at the stage before `to`; DOCUMENTATION needs a real checklist."""
    frm = FORWARD[FORWARD.index(to) - 1]
    if to == "DOCUMENTATION":
        set_stage(api, deal, "NEGOTIATION")
        upload_executed(api, deal, "ts.pdf", "term_sheet")
        assert move(api, deal, "DILIGENCE").status_code == 200
    else:
        set_stage(api, deal, frm)


@pytest.mark.parametrize("to, names, satisfy, override_role", MOVES,
                         ids=[m[0] for m in MOVES])
def test_each_forward_move_has_its_guards_and_they_pass_once_satisfied(
        api, to, names, satisfy, override_role):
    deal = make_deal(api)
    _prepare(api, deal, to)

    before = _guards(api, deal, to)
    assert set(before) == set(names)
    for g in before.values():
        assert g["description"] and g["severity"] == "blocking"
        assert g["override_role"] == override_role
    blocked = move(api, deal, to)
    assert blocked.status_code == 409 and blocked.json()["evaluations"], to
    assert any(not e["result"] for e in blocked.json()["evaluations"])

    satisfy(api, deal)
    assert all(g["result"] for g in _guards(api, deal, to).values()), _guards(api, deal, to)
    ok = move(api, deal, to)
    assert ok.status_code == 200, ok.text
    assert ok.json()["deal"]["stage"] == to
    assert {e["guard_name"] for e in ok.json()["evaluations"]} == set(names)


def test_t5_needs_both_a_counterparty_and_an_executed_nda(api):
    deal = make_deal(api)
    set_stage(api, deal, "MARKETED")
    link(api, deal, party(api)["id"], "lender")
    nda = upload(api, deal, "nda.pdf", "nda")  # on file but not executed
    assert _guards(api, deal, "MATCHED")["T5_counterparty_and_nda"]["result"] is False
    mark_executed(api, nda["id"])
    assert _guards(api, deal, "MATCHED")["T5_counterparty_and_nda"]["result"] is True


def test_executed_documents_only_count_while_marked_executed(api):
    deal = make_deal(api)
    set_stage(api, deal, "QUALIFIED")
    doc = upload(api, deal, "el.pdf", "engagement_letter")
    assert _guards(api, deal, "MANDATED")["T2_engagement_letter"]["result"] is False
    mark_executed(api, doc["id"])
    assert _guards(api, deal, "MANDATED")["T2_engagement_letter"]["result"] is True
    mark_executed(api, doc["id"], value=False)
    assert _guards(api, deal, "MANDATED")["T2_engagement_letter"]["result"] is False


def test_t6_needs_two_distinct_counterparties(api):
    deal = make_deal(api)
    set_stage(api, deal, "MATCHED")
    one = party(api)["id"]
    link(api, deal, one, "buyer")
    link(api, deal, one, "investor")  # the same party in two roles is still one party
    assert _guards(api, deal, "BID_AUCTION")["T6_two_counterparties"]["result"] is False
    link(api, deal, party(api)["id"], "lender")
    assert _guards(api, deal, "BID_AUCTION")["T6_two_counterparties"]["result"] is True


def test_t1_needs_a_linked_party_that_has_an_identifier(api):
    deal = make_deal(api)
    set_stage(api, deal, "ORIGINATED")
    link(api, deal, party(api, pan=None)["id"], "advisor")  # no identifier
    assert _guards(api, deal, "QUALIFIED")["T1_party_with_identifier"]["result"] is False
    link(api, deal, party(api)["id"], "buyer")
    assert _guards(api, deal, "QUALIFIED")["T1_party_with_identifier"]["result"] is True


def test_t3_wants_a_hard_criterion_not_just_any_mandate(api):
    deal = make_deal(api)
    set_stage(api, deal, "MANDATED")
    soft = {"title": "m", "side": "raise", "criteria": [
        {"criterion_key": "sector", "operator": "eq", "value": "infra", "hardness": "soft",
         "weight": 0.5}]}
    api.call("POST", f"/api/deals/{deal}/mandates", json=soft)
    assert _guards(api, deal, "PREPARED")["T3_hard_criterion"]["result"] is False
    api.call("POST", f"/api/deals/{deal}/mandates", json=HARD)
    assert _guards(api, deal, "PREPARED")["T3_hard_criterion"]["result"] is True


def test_t9_blockers_must_exist_and_none_may_be_open_requested_received_or_failed(api):
    deal = make_deal(api)
    set_stage(api, deal, "DILIGENCE")
    name = "T9_no_open_blockers"
    assert _guards(api, deal, "DOCUMENTATION")[name]["result"] is False  # no checklist yet
    ev = upload(api, deal, "e.pdf", "financial_statement")["id"]
    api.session.execute(text(
        "INSERT INTO diligence_item (deal_id, prompt, severity, status, evidence_doc_ids) "
        "VALUES (:d, 'b', 'blocker', 'open', '[]')"), {"d": deal})
    api.session.commit()
    item = api.session.execute(text("SELECT id FROM diligence_item")).scalar()
    for status in ("open", "requested", "received", "under_review", "failed"):
        api.session.execute(text("UPDATE diligence_item SET status = :s WHERE id = :i"),
                            {"s": status, "i": item})
        api.session.commit()
        assert _guards(api, deal, "DOCUMENTATION")[name]["result"] is False, status
    r = api.call("PATCH", f"/api/diligence/{item}",
                 json={"status": "satisfied", "evidence_doc_ids": [ev]})
    assert r.status_code == 200
    assert _guards(api, deal, "DOCUMENTATION")[name]["result"] is True


def test_t11_needs_a_condition_to_exist_and_all_to_be_cleared(api):
    deal = make_deal(api)
    set_stage(api, deal, "CONDITIONS_PRECEDENT")
    name = "T11_all_cps_cleared"
    assert _guards(api, deal, "CLOSED")[name]["result"] is False  # none recorded: not vacuous
    cp = _cp(api, deal)
    assert _guards(api, deal, "CLOSED")[name]["result"] is False
    api.call("PATCH", f"/api/conditions/{cp['id']}",
             json={"status": "waived", "waiver_justification": "not applicable"})
    assert _guards(api, deal, "CLOSED")[name]["result"] is True
    _cp(api, deal)  # a new open one reopens the guard
    assert _guards(api, deal, "CLOSED")[name]["result"] is False


def test_compliance_guards_are_overridden_by_compliance_not_the_dealmaker(api):
    deal = make_deal(api)
    set_stage(api, deal, "CONDITIONS_PRECEDENT")
    r = move(api, deal, "CLOSED", override_justification="please, it is signed")
    assert r.status_code == 409  # override_role is compliance; a dealmaker does not match
    no_why = move(api, deal, "CLOSED", user="priya")
    assert no_why.status_code == 403 and "compliance role cannot" in no_why.json()["detail"]
    ok = move(api, deal, "CLOSED", user="priya",
              override_justification="CP satisfied by regulator letter of 6 Oct, on file")
    assert ok.status_code == 200, ok.text
    ev = ok.json()["evaluations"]
    assert [(e["guard_name"], e["overridden_by"]) for e in ev] == [
        ("T11_all_cps_cleared", "priya")]
    hist = api.call("GET", f"/api/deals/{deal}").json()["history"][-1]
    assert hist["to_stage"] == "CLOSED" and hist["actor"] == "priya"


def test_compliance_cannot_make_an_ordinary_move_or_override_a_dealmaker_guard(api):
    deal = make_deal(api)
    # ORIGINATED -> QUALIFIED fails T1, whose override role is dealmaker
    r = move(api, deal, "QUALIFIED", user="priya", override_justification="trust me")
    assert r.status_code == 403
    set_stage(api, deal, "CONDITIONS_PRECEDENT")
    cp = _cp(api, deal)
    api.call("PATCH", f"/api/conditions/{cp['id']}",
             json={"status": "waived", "waiver_justification": "not applicable"})
    # every guard passes, so there is nothing to override: an ordinary move
    assert move(api, deal, "CLOSED", user="priya",
                override_justification="just closing").status_code == 403
    assert move(api, deal, "LAPSED", user="priya", reason_code="x").status_code == 403


def test_scripted_deal_reaches_closed_with_guard_rows_for_every_move(api):
    d = make_deal(api)
    for to, names, satisfy, _ in MOVES:
        assert move(api, d, to).status_code == 409, to  # each move starts blocked
        satisfy(api, d)
        r = move(api, d, to)
        assert r.status_code == 200, (to, r.text)
    deal = api.call("GET", f"/api/deals/{d}").json()
    assert deal["stage"] == "CLOSED" and deal["outcome"] == "closed_won"
    assert deal["closed_at"] is not None and deal["allowed_next"] == []

    # one history row per move, each linked to the evaluations that let it through
    rows = api.session.execute(text(
        "SELECT h.to_stage, COUNT(e.id), SUM(e.result) FROM deal_stage_history h "
        "LEFT JOIN stage_guard_evaluation e ON e.history_id = h.id WHERE h.deal_id = :d "
        "AND h.from_stage IS NOT NULL GROUP BY h.id ORDER BY h.id"), {"d": d}).all()
    assert [r[0] for r in rows] == FORWARD[1:]
    assert all(r[1] >= 1 and r[1] == r[2] for r in rows)  # every move has passing guard rows
    assert api.call("GET", "/api/audit/verify").json()["ok"] is True