"""Findings (DM.finding), checklist templates (DM.checklist_template), and the diligence
CHECK constraints at database level (F6.3)."""
import pytest
from sqlalchemy import text

from tests.integration.helpers import make_deal, set_stage, upload


def _item(api, deal, severity="material"):
    api.session.execute(text(
        "INSERT INTO diligence_item (deal_id, prompt, severity, status, evidence_doc_ids) "
        "VALUES (:d, 'Tax returns', :s, 'open', '[]')"), {"d": deal, "s": severity})
    api.session.commit()
    return api.session.execute(text("SELECT MAX(id) FROM diligence_item")).scalar()


def _finding(api, deal, item, user="bhavesh", **kw):
    body = {"diligence_item_id": item, "finding_type": "red_flag", "description": "Gap",
            "affects_valuation": False, **kw}
    return api.call("POST", f"/api/deals/{deal}/findings", user=user, json=body)


def test_finding_roundtrip_and_payload(api):
    deal = make_deal(api)
    item = _item(api, deal)
    r = _finding(api, deal, item, finding_type="adjustment", description="Normalise rent",
                 quantified_impact_inr=-25_000_000, affects_valuation=True)
    assert r.status_code == 201, r.text
    f = r.json()
    assert {"id", "diligence_item_id", "finding_type", "description", "quantified_impact_inr",
            "affects_valuation", "raised_by", "raised_at"} <= set(f)
    assert f["diligence_item_id"] == item and f["raised_by"] == "bhavesh"
    assert f["quantified_impact_inr"] == -25_000_000 and f["affects_valuation"] is True
    assert api.call("GET", f"/api/deals/{deal}/findings").json() == [f]
    audit = api.session.execute(text("SELECT payload, deal_id FROM audit_entries WHERE action "
                                     "= 'finding_created'")).one()
    assert '"adjustment"' in audit[0] and audit[1] == deal


def test_a_valuation_finding_needs_a_quantified_impact(api):
    deal = make_deal(api)
    item = _item(api, deal)
    assert _finding(api, deal, item, affects_valuation=True).status_code == 422
    assert _finding(api, deal, item).status_code == 201  # not affecting valuation: optional


@pytest.mark.parametrize("body", [{"finding_type": "rumour"}, {"description": ""},
                                  {"diligence_item_id": "x"}])
def test_finding_input_is_validated(api, body):
    deal = make_deal(api)
    item = _item(api, deal)
    assert _finding(api, deal, item, **body).status_code == 422


def test_a_finding_must_hang_off_an_item_on_this_deal(api):
    deal, other = make_deal(api), make_deal(api, "H-2")
    item = _item(api, other)
    assert _finding(api, deal, item).status_code == 404
    assert _finding(api, deal, 999).status_code == 404


def test_findings_are_walled_and_role_gated(api):
    deal = make_deal(api)
    item = _item(api, deal)
    assert api.call("GET", f"/api/deals/{deal}/findings", user="asha").status_code == 404
    api.add_member(deal, "asha")
    body = {"diligence_item_id": item, "finding_type": "observation", "description": "x",
            "affects_valuation": False}
    assert api.call("POST", f"/api/deals/{deal}/findings", user="asha", json=body
                    ).status_code == 201  # analysts raise findings
    for user in ("priya", "admin"):
        assert api.call("POST", f"/api/deals/{deal}/findings", user=user, json=body
                        ).status_code == 403
    assert api.call("GET", f"/api/deals/{deal}/findings", user="priya").status_code == 200


def test_the_database_requires_an_impact_for_a_valuation_finding(api):
    deal = make_deal(api)
    item = _item(api, deal)
    sql = ("INSERT INTO finding (diligence_item_id, finding_type, description, "
           "quantified_impact_inr, affects_valuation, raised_by, raised_at) VALUES "
           "(:i, :t, 'd', :q, :a, 'u', '2026-10-06')")
    with pytest.raises(Exception, match="ck_finding_impact_required"):
        api.session.execute(text(sql), {"i": item, "t": "red_flag", "q": None, "a": 1})
    api.session.rollback()
    with pytest.raises(Exception, match="ck_finding_type_valid"):
        api.session.execute(text(sql), {"i": item, "t": "gossip", "q": None, "a": 0})
    api.session.rollback()
    api.session.execute(text(sql), {"i": item, "t": "red_flag", "q": 10, "a": 1})
    api.session.execute(text(sql), {"i": item, "t": "red_flag", "q": None, "a": 0})


# ------------------------------------------------------------ diligence CHECKs at DB level

def _raw_item(api, deal, status, evidence="[]", waiver=None):
    api.session.execute(text(
        "INSERT INTO diligence_item (deal_id, prompt, severity, status, evidence_doc_ids, "
        "waiver_justification) VALUES (:d, 'p', 'standard', :s, :e, :w)"),
        {"d": deal, "s": status, "e": evidence, "w": waiver})


def test_satisfied_without_evidence_is_refused_by_the_database(api):
    deal = make_deal(api)
    for evidence in ("[]", "null"):
        with pytest.raises(Exception, match="ck_satisfied_needs_evidence"):
            _raw_item(api, deal, "satisfied", evidence)
        api.session.rollback()
    _raw_item(api, deal, "satisfied", "[1]")  # with evidence it is fine


def test_waived_without_justification_is_refused_by_the_database(api):
    deal = make_deal(api)
    with pytest.raises(Exception, match="ck_waived_needs_justification"):
        _raw_item(api, deal, "waived")
    api.session.rollback()
    _raw_item(api, deal, "waived", waiver="not applicable")


def test_updating_an_item_into_satisfied_or_waived_hits_the_same_checks(api):
    deal = make_deal(api)
    item = _item(api, deal)
    with pytest.raises(Exception, match="ck_satisfied_needs_evidence"):
        api.session.execute(text("UPDATE diligence_item SET status = 'satisfied' "
                                 "WHERE id = :i"), {"i": item})
    api.session.rollback()
    with pytest.raises(Exception, match="ck_waived_needs_justification"):
        api.session.execute(text("UPDATE diligence_item SET status = 'waived' "
                                 "WHERE id = :i"), {"i": item})
    api.session.rollback()


def test_a_waived_condition_needs_its_justification_in_the_database_too(api):
    deal = make_deal(api)
    with pytest.raises(Exception, match="ck_cp_waived_needs_justification"):
        api.session.execute(text(
            "INSERT INTO condition_precedent (deal_id, description, cp_type, status) "
            "VALUES (:d, 'x', 'y', 'waived')"), {"d": deal})
    api.session.rollback()


# ------------------------------------------------------------------ checklist templates

def test_item_templates_belong_to_a_template_with_a_layer_and_version(api):
    templates = api.session.execute(text(
        "SELECT id, transaction_class, layer, version, name FROM checklist_template "
        "ORDER BY id")).all()
    assert [(t[1], t[2], t[3]) for t in templates] == [(None, "base", 1), ("DEBT", "subclass", 1),
                                                       ("ALLIANCE", "subclass", 1)]
    assert all(t[4] for t in templates)
    orphans = api.session.execute(text(
        "SELECT COUNT(*) FROM checklist_item_template i LEFT JOIN checklist_template t "
        "ON t.id = i.template_id WHERE t.id IS NULL")).scalar()
    assert orphans == 0
    mismatched = api.session.execute(text(
        "SELECT COUNT(*) FROM checklist_item_template i JOIN checklist_template t ON "
        "t.id = i.template_id WHERE i.transaction_class IS NOT t.transaction_class")).scalar()
    assert mismatched == 0


def test_template_rows_are_checked(api):
    with pytest.raises(Exception, match="ck_layer_valid"):
        api.session.execute(text("INSERT INTO checklist_template (layer, version, name) "
                                 "VALUES ('galaxy', 1, 'x')"))
    api.session.rollback()
    with pytest.raises(Exception, match="FOREIGN KEY"):
        api.session.execute(text(
            "INSERT INTO checklist_item_template (template_id, category, prompt, "
            "default_severity) VALUES (999, 'c', 'p', 'standard')"))
    api.session.rollback()
    for layer in ("base", "subclass", "vertical", "jurisdiction"):
        api.session.execute(text("INSERT INTO checklist_template (layer, version, name) "
                                 "VALUES (:l, 1, 'x')"), {"l": layer})


def test_entering_diligence_instantiates_items_from_the_deals_templates(api):
    deal = make_deal(api)
    set_stage(api, deal, "NEGOTIATION")
    doc = upload(api, deal, "ts.pdf", "term_sheet")
    api.call("PATCH", f"/api/documents/{doc['id']}", json={"is_executed": True})
    assert api.call("POST", f"/api/deals/{deal}/transition",
                    json={"to_stage": "DILIGENCE"}).status_code == 200
    items = api.call("GET", f"/api/deals/{deal}/diligence").json()
    assert len(items) == 7  # base items and the DEBT subclass items
    assert all(i["template_id"] for i in items)