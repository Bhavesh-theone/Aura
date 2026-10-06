"""Regulatory flags and compliance sign-off (R3.8), and the T9 guard that uses them."""
import pytest
from sqlalchemy import text

from tests.integration.helpers import make_deal, move, set_stage, upload_executed

SIGNOFF_KEYS = {"id", "deal_id", "signed_by", "note", "signed_at"}


def _signoff_guard(api, deal):
    r = api.call("GET", f"/api/deals/{deal}/guards", params={"to_stage": "DOCUMENTATION"})
    return {g["guard_name"]: g["result"] for g in r.json()}["T9_compliance_signoff"]


def test_deals_carry_regulatory_flags_defaulting_to_empty(api):
    deal = make_deal(api)
    assert api.call("GET", f"/api/deals/{deal}").json()["regulatory_flags"] == []
    assert api.call("GET", "/api/deals").json()[0]["regulatory_flags"] == []
    created = api.call("POST", "/api/deals", json={"external_id": "N-1", "name": "n",
                                                   "transaction_class": "DEBT"})
    assert created.json()["regulatory_flags"] == []


@pytest.mark.parametrize("user", ["bhavesh", "priya"])
def test_dealmaker_and_compliance_set_flags(api, user):
    deal = make_deal(api)
    r = api.call("PATCH", f"/api/deals/{deal}", user=user,
                 json={"regulatory_flags": ["SEBI takeover code", " RBI FEMA ", "RBI FEMA", ""]})
    assert r.status_code == 200
    assert r.json()["regulatory_flags"] == ["SEBI takeover code", "RBI FEMA"]
    assert api.call("GET", f"/api/deals/{deal}").json()["regulatory_flags"] == [
        "SEBI takeover code", "RBI FEMA"]
    audit = api.session.execute(text("SELECT actor, payload FROM audit_entries WHERE action "
                                     "= 'deal_flags_updated'")).one()
    assert audit[0] == user and '"RBI FEMA"' in audit[1]
    assert api.call("PATCH", f"/api/deals/{deal}", user=user,
                    json={"regulatory_flags": []}).json()["regulatory_flags"] == []


def test_flags_are_validated_and_role_gated(api):
    deal = make_deal(api)
    api.add_member(deal, "asha")
    assert api.call("PATCH", f"/api/deals/{deal}", json={"regulatory_flags": "SEBI"}
                    ).status_code == 422
    assert api.call("PATCH", f"/api/deals/{deal}", json={"regulatory_flags": [1]}
                    ).status_code == 422
    for user in ("asha", "admin"):
        assert api.call("PATCH", f"/api/deals/{deal}", user=user,
                        json={"regulatory_flags": ["SEBI"]}).status_code == 403
    assert api.call("PATCH", "/api/deals/999", json={"regulatory_flags": []}).status_code == 404


def test_signoff_is_compliance_only_and_listed(api):
    deal = make_deal(api)
    api.add_member(deal, "asha")
    for user in ("bhavesh", "asha", "admin"):
        assert api.call("POST", f"/api/deals/{deal}/signoffs", user=user,
                        json={"note": "ok"}).status_code == 403
    assert api.call("GET", f"/api/deals/{deal}/signoffs").json() == []
    r = api.call("POST", f"/api/deals/{deal}/signoffs", user="priya",
                 json={"note": "Takeover code filing reviewed"})
    assert r.status_code == 201
    s = r.json()
    assert set(s) == SIGNOFF_KEYS and s["signed_by"] == "priya" and s["deal_id"] == deal
    assert s["note"] == "Takeover code filing reviewed" and s["signed_at"]
    assert api.call("GET", f"/api/deals/{deal}/signoffs", user="asha").json() == [s]
    assert api.call("GET", f"/api/deals/{deal}/signoffs", user="admin").status_code == 404
    audit = api.session.execute(text("SELECT actor, deal_id FROM audit_entries WHERE action = "
                                     "'deal_signoff'")).one()
    assert tuple(audit) == ("priya", deal)


def test_signoffs_are_walled(api):
    deal = make_deal(api)
    api.call("DELETE", f"/api/deals/{deal}/members", user="priya", json={"username": "priya"})
    assert api.call("POST", f"/api/deals/{deal}/signoffs", user="priya",
                    json={"note": "x"}).status_code == 404
    assert api.call("GET", f"/api/deals/{deal}/signoffs", user="priya").status_code == 404


def test_t9_waits_for_a_signoff_exactly_when_the_deal_has_flags(api):
    deal = make_deal(api)
    set_stage(api, deal, "DILIGENCE")
    assert _signoff_guard(api, deal) is True  # no flags: nothing to sign
    api.call("PATCH", f"/api/deals/{deal}", json={"regulatory_flags": ["SEBI"]})
    assert _signoff_guard(api, deal) is False
    api.call("POST", f"/api/deals/{deal}/signoffs", user="priya", json={"note": "cleared"})
    assert _signoff_guard(api, deal) is True


def test_a_flagged_deal_cannot_leave_diligence_without_compliance(api):
    deal = make_deal(api)
    set_stage(api, deal, "NEGOTIATION")
    upload_executed(api, deal, "ts.pdf", "term_sheet")
    assert move(api, deal, "DILIGENCE").status_code == 200
    evidence = upload_executed(api, deal, "ev.pdf", "financial_statement")["id"]
    for item in api.call("GET", f"/api/deals/{deal}/diligence").json():
        if item["severity"] == "blocker":
            api.call("PATCH", f"/api/diligence/{item['id']}",
                     json={"status": "satisfied", "evidence_doc_ids": [evidence]})
    api.call("PATCH", f"/api/deals/{deal}", json={"regulatory_flags": ["FEMA"]})

    blocked = move(api, deal, "DOCUMENTATION")
    assert blocked.status_code == 409
    failed = [e["guard_name"] for e in blocked.json()["evaluations"] if not e["result"]]
    assert failed == ["T9_compliance_signoff"]
    api.call("POST", f"/api/deals/{deal}/signoffs", user="priya", json={"note": "cleared"})
    assert move(api, deal, "DOCUMENTATION").status_code == 200