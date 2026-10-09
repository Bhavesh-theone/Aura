import pytest
from sqlalchemy import text

from aura.core.domain.enums import DocClass, PartyType
from tests.integration.helpers import make_deal, run_worker, set_stage, submit, upload

DOC_CLASSES = ["financial_statement", "cap_table", "board_resolution", "moa_aoa", "term_sheet",
               "spa", "shpa", "valuation_report", "tax_return", "litigation_summary",
               "env_clearance", "engagement_letter", "nda", "bank_statement", "gst_return",
               "charge_document", "land_title"]
PARTY_TYPES = ["company", "llp", "fund", "trust", "individual", "government_body",
               "foreign_entity", "partnership", "sole_prop", "huf"]


def test_enums_match_the_frontend_vocabulary_exactly():
    assert sorted(c.value for c in DocClass) == sorted(DOC_CLASSES)
    assert sorted(p.value for p in PartyType) == sorted(PARTY_TYPES)


@pytest.mark.parametrize("doc_class", DOC_CLASSES)
def test_every_doc_class_is_accepted(api, doc_class):
    deal = make_deal(api)
    assert upload(api, deal, "f.pdf", doc_class)["doc_class"] == doc_class


@pytest.mark.parametrize("old", ["teaser", "sha", "dd_report", "other", "financial_statements"])
def test_removed_doc_classes_are_rejected(api, old):
    deal = make_deal(api)
    r = api.call("POST", f"/api/deals/{deal}/documents", files={"file": ("f.pdf", b"x")},
                 data={"doc_class": old})
    assert r.status_code == 422


@pytest.mark.parametrize("party_type", PARTY_TYPES)
def test_every_party_type_is_accepted(api, party_type):
    r = api.call("POST", "/api/parties", json={"party_type": party_type, "display_name": "P"})
    assert r.status_code == 201 and r.json()["party_type"] == party_type


def test_removed_party_type_is_rejected(api):
    r = api.call("POST", "/api/parties", json={"party_type": "institution",
                                               "display_name": "P"})
    assert r.status_code == 422


def test_database_checks_agree_with_the_enums(api):
    deal = make_deal(api)
    for sql, params in [
        ("INSERT INTO party (party_type, display_name, created_at) VALUES "
         "('institution', 'x', '2026-01-01')", {}),
        ("INSERT INTO document (deal_id, doc_class, filename, sha256, byte_size, current_version, "
         "contains_upsi, sensitivity, uploaded_by, uploaded_at, class_confirmed) VALUES "
         "(:d, 'teaser', 'f', 'x', 1, 1, false, 2, 'u', '2026-01-01', false)", {"d": deal})]:
        with pytest.raises(Exception, match="ck_"):
            api.session.execute(text(sql), params)
        api.session.rollback()


def test_dashboard_summary(api):
    empty = api.call("GET", "/api/dashboard/summary").json()
    assert empty["open_deals"] == 0 and empty["recent_activity"] == []

    d1 = make_deal(api, "S-1")
    d2 = make_deal(api, "S-2")
    api.call("POST", "/api/deals", json={"external_id": "S-3", "name": "Alliance",
                                         "transaction_class": "ALLIANCE"})
    set_stage(api, d1, "QUALIFIED")
    api.call("POST", f"/api/deals/{d2}/transition",
             json={"to_stage": "WITHDRAWN", "reason_code": "client_pulled"})
    api.session.execute(text(
        "INSERT INTO diligence_item (deal_id, prompt, severity, status, evidence_doc_ids) "
        "VALUES (:d, 'a', 'blocker', 'open', '[]'), (:d, 'b', 'blocker', 'satisfied', '[1]'), "
        "(:d, 'c', 'standard', 'open', '[]'), (:d, 'd', 'blocker', 'requested', '[]')"),
        {"d": d1})
    api.session.commit()
    submit(api, {"brief": "intro"}, deal_id=d1)
    run_worker(api)

    s = api.call("GET", "/api/dashboard/summary").json()
    assert s["open_deals"] == 2  # the withdrawn deal is not open
    assert s["deals_by_class"] == {"DEBT": 1, "ALLIANCE": 1}
    # every deal is counted by stage, the withdrawn one included
    assert s["deals_by_stage"] == {"QUALIFIED": 1, "ORIGINATED": 1, "WITHDRAWN": 1}
    assert s["closed_deals"] == 0 and s["ended_deals"] == 1
    assert s["decisions_waiting"] == 1
    assert s["blockers_open"] == 2
    activity = s["recent_activity"]
    assert 0 < len(activity) <= 10
    assert activity == sorted(activity, key=lambda e: e["id"], reverse=True)
    assert {"id", "actor", "action", "payload", "created_at", "deal_id"} <= set(activity[0])
    assert api.client.get("/api/dashboard/summary").status_code == 401


def test_recent_activity_is_capped_at_ten(api):
    deal = make_deal(api)
    for i in range(12):
        upload(api, deal, f"f{i}.pdf", "nda")
    assert len(api.call("GET", "/api/dashboard/summary").json()["recent_activity"]) == 10
