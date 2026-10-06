"""Extractions and the confidence gate on feeding a valuation (PRD F5.5)."""
import pytest
from sqlalchemy import text

from tests.integration.helpers import DIRECTIVE, make_deal, run_worker, submit, upload

CONFIDENT = b"Audited summary\nRevenue: 1,200,000,000\nEBITDA: 300,000,000\nNet debt: 150,000,000\n"
DOUBTFUL = b"Revenue: 5\nnothing else of use here"
KEYS = {"id", "document_id", "schema_name", "payload", "confidence", "feeds_valuation",
        "human_verified_by", "human_verified_at", "created_at"}


def _extract(api, deal, doc, user="bhavesh"):
    job = submit(api, {"capability": "extract_financials", "document_id": doc["id"]},
                 deal_id=deal, user=user)
    run_worker(api)
    return job


def _insert(api, **kw):
    cols = dict(document_id=1, version=1, schema_name="financials.v1", payload="{}",
                confidence=0.5, feeds_valuation=0, human_verified_by=None,
                human_verified_at=None, model_run_id=None, created_at="2026-10-06")
    cols.update(kw)
    api.session.execute(text(
        "INSERT INTO extraction (" + ", ".join(cols) + ") VALUES (:" + ", :".join(cols) + ")"),
        cols)


# ------------------------------------------------------------------ the database gate

def test_the_database_refuses_an_unverified_low_confidence_extraction_that_feeds_valuation(api):
    deal = make_deal(api)
    upload(api, deal)
    with pytest.raises(Exception, match="ck_extraction_valuation_gate"):
        _insert(api, confidence=0.94, feeds_valuation=1)
    api.session.rollback()

    _insert(api, confidence=0.94, feeds_valuation=0)  # recorded, not feeding: fine
    _insert(api, confidence=0.95, feeds_valuation=1)  # confident enough on its own
    _insert(api, confidence=0.40, feeds_valuation=1, human_verified_by="bhavesh",
            human_verified_at="2026-10-06")  # a person vouched
    api.session.commit()
    assert api.session.execute(text("SELECT COUNT(*) FROM extraction")).scalar() == 3


@pytest.mark.parametrize("confidence", [-0.1, 1.5])
def test_confidence_is_a_probability(api, confidence):
    deal = make_deal(api)
    upload(api, deal)
    with pytest.raises(Exception, match="ck_extraction_confidence_range"):
        _insert(api, confidence=confidence)
    api.session.rollback()


# ------------------------------------------------------------------ the agent capability

def test_a_confident_extraction_is_recorded_without_a_handoff_and_feeds_nothing_yet(api):
    deal = make_deal(api)
    doc = upload(api, deal, "fy24.txt", "financial_statement", CONFIDENT)
    job = _extract(api, deal, doc)
    assert api.call("GET", f"/api/jobs/{job['id']}").json()["status"] == "complete"
    assert api.call("GET", "/api/handoffs").json() == []

    (e,) = api.call("GET", f"/api/deals/{deal}/extractions").json()
    assert set(e) == KEYS
    assert e["document_id"] == doc["id"] and e["schema_name"] == "financials.v1"
    assert e["confidence"] == 0.98 and e["feeds_valuation"] is False
    assert e["payload"] == {"revenue_inr": 1200000000.0, "ebitda_inr": 300000000.0,
                            "net_debt_inr": 150000000.0}
    assert e["human_verified_by"] is None and e["human_verified_at"] is None
    row = api.session.execute(text("SELECT version, model_run_id FROM extraction")).one()
    assert row[0] == 1 and row[1] == api.session.execute(
        text("SELECT id FROM agent_run")).scalar()  # tied to the run that read it


def test_a_doubtful_extraction_raises_a_confidence_handoff_with_verify_and_discard(api):
    deal = make_deal(api)
    doc = upload(api, deal, "thin.txt", "financial_statement", DOUBTFUL)
    job = _extract(api, deal, doc)
    assert api.call("GET", f"/api/jobs/{job['id']}").json()["status"] == "awaiting_approval"
    (h,) = api.call("GET", "/api/handoffs").json()
    assert h["trigger"] == "confidence_below_threshold" and h["task_type"] == "extract_financials"
    assert [o["id"] for o in h["context_package"]["decision_required"]["options"]] == [
        "verify", "discard"]
    (e,) = api.call("GET", f"/api/deals/{deal}/extractions").json()
    assert e["confidence"] < 0.95 and e["feeds_valuation"] is False


def _doubtful_handoff(api):
    deal = make_deal(api)
    doc = upload(api, deal, "thin.txt", "financial_statement", DOUBTFUL)
    job = _extract(api, deal, doc)
    (h,) = api.call("GET", "/api/handoffs").json()
    return deal, job, h


def test_verifying_through_the_handoff_marks_the_extraction_and_the_job_completes(api):
    deal, job, h = _doubtful_handoff(api)
    r = api.call("POST", f"/api/handoffs/{h['id']}/resolve", json={**DIRECTIVE,
                                                                   "decision": "verify"})
    assert r.status_code == 200, r.text
    (e,) = api.call("GET", f"/api/deals/{deal}/extractions").json()
    assert e["feeds_valuation"] is True and e["human_verified_by"] == "bhavesh"
    run_worker(api)
    assert api.call("GET", f"/api/jobs/{job['id']}").json()["status"] == "complete"


def test_discarding_leaves_the_extraction_out_of_valuation(api):
    deal, job, h = _doubtful_handoff(api)
    api.call("POST", f"/api/handoffs/{h['id']}/resolve",
             json={**DIRECTIVE, "decision": "discard"})
    (e,) = api.call("GET", f"/api/deals/{deal}/extractions").json()
    assert e["feeds_valuation"] is False and e["human_verified_by"] is None
    assert api.call("GET", f"/api/jobs/{job['id']}").json()["status"] == "rejected"


def test_the_capability_needs_a_document_on_the_deal(api):
    deal, other = make_deal(api), make_deal(api, "H-2")
    elsewhere = upload(api, other)
    r = api.call("POST", "/api/jobs", json={"deal_id": deal, "inputs": {
        "capability": "extract_financials", "document_id": elsewhere["id"]}})
    assert r.status_code == 404
    assert api.call("POST", "/api/jobs", json={"deal_id": None, "inputs": {
        "capability": "extract_financials", "document_id": 1}}).status_code == 422


# ------------------------------------------------------------------ the verify endpoint

def test_verify_endpoint_by_dealmaker_or_analyst(api):
    deal = make_deal(api)
    api.add_member(deal, "asha")
    doc = upload(api, deal, "fy.txt", "financial_statement", CONFIDENT)
    _extract(api, deal, doc)
    (e,) = api.call("GET", f"/api/deals/{deal}/extractions", user="asha").json()

    assert api.call("POST", f"/api/extractions/{e['id']}/verify", user="priya"
                    ).status_code == 403
    assert api.call("POST", f"/api/extractions/{e['id']}/verify", user="admin"
                    ).status_code == 403
    r = api.call("POST", f"/api/extractions/{e['id']}/verify", user="asha")
    assert r.status_code == 200 and set(r.json()) == KEYS
    assert r.json()["feeds_valuation"] is True and r.json()["human_verified_by"] == "asha"
    assert r.json()["human_verified_at"] is not None
    assert api.call("POST", f"/api/extractions/{e['id']}/verify").status_code == 409
    assert api.call("POST", "/api/extractions/999/verify").status_code == 404
    actions = api.session.execute(text("SELECT action FROM audit_entries WHERE action LIKE "
                                       "'extraction_%' ORDER BY id")).scalars().all()
    assert actions == ["extraction_created", "extraction_verified"]


def test_extractions_are_walled(api):
    deal = make_deal(api)
    doc = upload(api, deal, "fy.txt", "financial_statement", CONFIDENT)
    _extract(api, deal, doc)
    (e,) = api.call("GET", f"/api/deals/{deal}/extractions").json()
    assert api.call("GET", f"/api/deals/{deal}/extractions", user="asha").status_code == 404
    assert api.call("POST", f"/api/extractions/{e['id']}/verify", user="asha"
                    ).status_code == 404
    assert api.call("GET", "/api/deals/999/extractions").status_code == 404