import hashlib

import pytest
from sqlalchemy import text

from tests.integration.helpers import set_stage

DEAL = {"external_id": "T-1", "name": "Test Deal", "transaction_class": "DEBT"}


def _new_deal(api):
    r = api.call("POST", "/api/deals", json=DEAL)
    assert r.status_code == 201, r.text
    return r.json()


def _move(api, deal_id, to, user="bhavesh", **body):
    return api.call("POST", f"/api/deals/{deal_id}/transition", user=user,
                    json={"to_stage": to, **body})


def _upload(api, deal_id, doc_class, content=b"hello", upsi=False):
    return api.call("POST", f"/api/deals/{deal_id}/documents",
                    files={"file": ("f.pdf", content)},
                    data={"doc_class": doc_class, "contains_upsi": str(upsi).lower()})


def test_create_deal_starts_originated_with_history(api):
    deal = _new_deal(api)
    assert deal["stage"] == "ORIGINATED" and deal["outcome"] is None
    detail = api.call("GET", f"/api/deals/{deal['id']}").json()
    assert detail["history"][0]["to_stage"] == "ORIGINATED"
    assert "QUALIFIED" in detail["allowed_next"] and "MATCHED" not in detail["allowed_next"]
    assert api.call("POST", "/api/deals", json=DEAL).status_code == 409
    assert len(api.call("GET", "/api/deals").json()) == 1


def test_illegal_jump_and_missing_reason(api):
    deal = _new_deal(api)
    r = _move(api, deal["id"], "MATCHED")
    assert r.status_code == 409 and r.json()["evaluations"] == []
    assert _move(api, deal["id"], "LAPSED").status_code == 422


def test_blocked_transition_then_dealmaker_override(api):
    deal = _new_deal(api)
    set_stage(api, deal["id"], "QUALIFIED")

    dry = api.call("GET", f"/api/deals/{deal['id']}/guards", params={"to_stage": "MANDATED"})
    assert dry.status_code == 200 and dry.json()[0]["result"] is False
    assert dry.json()[0]["override_role"] == "dealmaker"
    assert api.session.execute(text("SELECT COUNT(*) FROM stage_guard_evaluation")).scalar() == 0

    r = _move(api, deal["id"], "MANDATED")
    assert r.status_code == 409
    body = r.json()
    assert body["evaluations"][0]["guard_name"] == "T2_engagement_letter"
    assert body["evaluations"][0]["result"] is False
    assert body["evaluations"][0]["override_role"] == "dealmaker"

    api.add_member(deal["id"], "asha")
    # an analyst cannot move a deal at all, with or without a justification
    assert _move(api, deal["id"], "MANDATED", user="asha",
                 override_justification="trust me").status_code == 403
    # the dealmaker must justify
    assert _move(api, deal["id"], "MANDATED").status_code == 409
    ok = _move(api, deal["id"], "MANDATED", override_justification="signed on paper")
    assert ok.status_code == 200
    assert ok.json()["evaluations"][0]["overridden_by"] == "bhavesh"
    rows = api.session.execute(text("SELECT result, overridden_by, history_id FROM "
                                    "stage_guard_evaluation ORDER BY id")).all()
    assert len(rows) == 3  # every real attempt recorded, the dry run and the 403 wrote nothing
    assert [r[1] for r in rows] == [None, None, "bhavesh"]
    # only the move that succeeded is linked to its history row
    history_id = api.session.execute(text(
        "SELECT id FROM deal_stage_history WHERE to_stage = 'MANDATED'")).scalar()
    assert [r[2] for r in rows] == [None, None, history_id]


def test_regression_requires_reason_and_is_flagged(api):
    d = _new_deal(api)["id"]
    api.session.execute(text("UPDATE deals SET stage = 'MATCHED' WHERE id = :i"), {"i": d})
    api.session.commit()
    assert _move(api, d, "MARKETED").status_code == 422
    assert _move(api, d, "MARKETED", reason_code="buyer_dropped").status_code == 200
    hist = api.call("GET", f"/api/deals/{d}").json()["history"]
    assert hist[-1]["is_regression"] is True and hist[-1]["reason_code"] == "buyer_dropped"


def test_history_is_immutable(api):
    d = _new_deal(api)["id"]
    for sql in ("UPDATE deal_stage_history SET actor = 'evil'", "DELETE FROM deal_stage_history"):
        # the app role was never granted UPDATE/DELETE on the history (the owner-side
        # append-only trigger is covered in test_rls.py)
        with pytest.raises(Exception, match="permission denied"):
            api.session.execute(text(sql))
        api.session.rollback()
    assert api.call("GET", f"/api/deals/{d}").json()["history"][0]["actor"] == "bhavesh"


def test_terminal_check_constraint(api):
    d = _new_deal(api)["id"]
    with pytest.raises(Exception, match="ck_deal_terminal_consistent"):
        api.session.execute(text("UPDATE deals SET stage = 'CLOSED' WHERE id = :i"), {"i": d})
    api.session.rollback()


def test_broken_guard_fails_closed(api):
    d = _new_deal(api)["id"]
    api.session.execute(text(
        "INSERT INTO stage_guard (from_stage, to_stage, guard_name, sql_text, severity, active)"
        " VALUES ('ORIGINATED', 'QUALIFIED', 'bad', 'SELECT * FROM nope', 'blocking', true)"))
    api.session.commit()
    r = _move(api, d, "QUALIFIED")
    assert r.status_code == 409
    broken = [e for e in r.json()["evaluations"] if e["guard_name"] == "bad"]
    assert "error" in broken[0]["detail"]


def test_parties_validation_and_duplicates(api):
    body = {"party_type": "company", "display_name": "A",
            "identifiers": [{"scheme": "PAN", "value": "BAD"}]}
    assert api.call("POST", "/api/parties", json=body).status_code == 422
    body["identifiers"] = [{"scheme": "CIN", "value": "U12345MH2020PTC123456"}]
    assert api.call("POST", "/api/parties", json=body).status_code == 201
    assert api.call("POST", "/api/parties", json={**body, "display_name": "B"}).status_code == 409
    listed = api.call("GET", "/api/parties").json()
    assert len(listed) == 1 and listed[0]["identifiers"][0]["scheme"] == "CIN"


def test_documents_upsi_download_and_access_log(api):
    d = _new_deal(api)["id"]
    r = _upload(api, d, "nda", b"secret", upsi=True)
    assert r.status_code == 201
    doc = r.json()
    assert doc["sensitivity"] == 4 and doc["sha256"] == hashlib.sha256(b"secret").hexdigest()
    assert doc["current_version"] == 1 and doc["class_confirmed"] is False
    assert doc["is_executed"] is False and "version" not in doc
    # the same filename on the same deal is a new version of the same document
    again = _upload(api, d, "nda", b"secret2").json()
    assert again["id"] == doc["id"] and again["current_version"] == 2
    assert again["sha256"] == hashlib.sha256(b"secret2").hexdigest()

    dl = api.call("GET", f"/api/documents/{doc['id']}/download")
    assert dl.status_code == 200 and dl.content == b"secret2"
    n = api.session.execute(text("SELECT COUNT(*) FROM doc_access_log")).scalar()
    assert n == 1
    assert len(api.call("GET", f"/api/deals/{d}/documents").json()) == 1
    with pytest.raises(Exception, match="permission denied"):  # the app cannot erase it
        api.session.execute(text("DELETE FROM doc_access_log"))
    api.session.rollback()


def test_upsi_check_constraint(api):
    d = _new_deal(api)["id"]
    with pytest.raises(Exception, match="ck_upsi_sensitivity"):
        api.session.execute(text(
            "INSERT INTO document (deal_id, doc_class, filename, sha256, byte_size, "
            "current_version, contains_upsi, sensitivity, uploaded_by, uploaded_at, "
            "class_confirmed) VALUES (:d, 'nda', 'f', 'x', 1, 1, true, 2, 'u', '2026-01-01', "
            "false)"),
            {"d": d})
    api.session.rollback()


def test_mandates(api):
    d = _new_deal(api)["id"]
    url = f"/api/deals/{d}/mandates"

    def crit(**kw):
        return {"criterion_key": "sector", "operator": "eq", "value": "infra",
                "hardness": "hard", **kw}

    for bad_crit in (crit(hardness="soft"),                       # soft without weight
                     crit(hardness="soft", weight=1.5),           # weight outside 0..1
                     crit(operator="between", value=[1]),         # between needs two
                     crit(operator="in", value=[]),               # in needs a list
                     crit(operator="gte", value="lots"),          # gte needs a number
                     crit(operator="approx")):                    # unknown operator
        body = {"title": "M", "side": "raise", "criteria": [bad_crit]}
        assert api.call("POST", url, json=body).status_code == 422, bad_crit
    assert api.call("POST", url, json={"title": "M", "side": "lend"}).status_code == 422
    assert api.call("POST", url, json={"title": "M"}).status_code == 422  # side required
    good = {"title": "M", "side": "raise", "criteria": [
        crit(criterion_key="ticket_size_inr", operator="between",
             value=[400_000_000, 500_000_000]),
        crit(operator="in", value=["textiles", "apparel"], hardness="soft", weight=0.5),
        crit(criterion_key="geography", operator="not_in", value=["sanctioned"],
             hardness="preference")]}
    made = api.call("POST", url, json=good)
    assert made.status_code == 201 and made.json()["status"] == "active"
    listed = api.call("GET", url).json()
    assert len(listed) == 1 and listed[0]["side"] == "raise"
    sent = [{"weight": None, **c} for c in good["criteria"]]
    assert listed[0]["criteria"] == sent  # JSON values come back as sent


def test_deal_endpoints_require_auth_and_404(api):
    assert api.client.get("/api/deals").status_code == 401
    assert api.call("GET", "/api/deals/999").status_code == 404
