from sqlalchemy import text

from tests.integration.helpers import make_deal

MNA_DEAL = {"external_id": "P-1", "name": "Profile Deal", "transaction_class": "MNA"}
PROFILE = {"structure": "share_purchase", "stake_pct": 51, "cci_route": "green_channel",
           "enterprise_value_inr": 2_500_000_000}


def _create(api, **extra):
    r = api.call("POST", "/api/deals", json={**MNA_DEAL, **extra})
    assert r.status_code == 201, r.text
    return r.json()


def _profile_audits(api, deal_id):
    return api.session.execute(text(
        "SELECT actor, payload FROM audit_entries WHERE deal_id = :d "
        "AND action = 'deal_profile_updated' ORDER BY id"), {"d": deal_id}).all()


def test_create_with_profile_and_read_it_back(api):
    deal = _create(api, profile=PROFILE)
    assert deal["profile"] == PROFILE and deal["profile_schema_version"] == 1
    detail = api.call("GET", f"/api/deals/{deal['id']}").json()
    assert detail["profile"] == PROFILE and detail["profile_schema_version"] == 1
    listed = api.call("GET", "/api/deals").json()
    assert listed[0]["profile"] == PROFILE


def test_create_without_profile_starts_empty(api):
    deal_id = make_deal(api)
    detail = api.call("GET", f"/api/deals/{deal_id}").json()
    assert detail["profile"] == {} and detail["profile_schema_version"] == 1


def test_create_with_invalid_profile_is_422_and_creates_nothing(api):
    r = api.call("POST", "/api/deals", json={**MNA_DEAL, "profile": {"stake_pct": 120}})
    assert r.status_code == 422 and "profile.stake_pct" in r.json()["detail"]
    r = api.call("POST", "/api/deals", json={**MNA_DEAL, "profile": {},
                                             "profile_schema_version": 9})
    assert r.status_code == 422
    assert api.call("GET", "/api/deals").json() == []


def test_analyst_updates_profile_and_it_is_audited(api):
    deal = _create(api, profile=PROFILE)
    api.add_member(deal["id"], "asha")
    new = {**PROFILE, "stake_pct": 76, "side": "buy_side"}
    del new["cci_route"]
    r = api.call("PATCH", f"/api/deals/{deal['id']}", user="asha", json={"profile": new})
    assert r.status_code == 200, r.text
    assert r.json()["profile"] == new
    assert r.json()["regulatory_flags"] == []
    assert api.call("GET", f"/api/deals/{deal['id']}").json()["profile"] == new
    (actor, payload), = _profile_audits(api, deal["id"])
    assert actor == "asha"
    assert payload == {"profile_schema_version": 1,
                       "changed_keys": ["cci_route", "side", "stake_pct"]}


def test_compliance_cannot_edit_profile(api):
    deal = _create(api, profile=PROFILE)
    r = api.call("PATCH", f"/api/deals/{deal['id']}", user="priya",
                 json={"profile": {"stake_pct": 10}})
    assert r.status_code == 403
    assert api.call("GET", f"/api/deals/{deal['id']}").json()["profile"] == PROFILE


def test_invalid_profile_update_is_422_and_changes_nothing(api):
    deal = _create(api, profile=PROFILE)
    for body in ({"profile": {"stake_pct": -1}},
                 {"profile": {"not_a_field": True}},
                 {"profile": {"stake_pct": 10}, "profile_schema_version": 2},
                 # flags are valid, the profile is not: neither is saved
                 {"regulatory_flags": ["FEMA"], "profile": {"stake_pct": "lots"}},
                 {}):
        r = api.call("PATCH", f"/api/deals/{deal['id']}", json=body)
        assert r.status_code == 422, (body, r.text)
    detail = api.call("GET", f"/api/deals/{deal['id']}").json()
    assert detail["profile"] == PROFILE and detail["regulatory_flags"] == []
    assert _profile_audits(api, deal["id"]) == []


def test_profile_update_on_a_deal_you_cannot_see_is_404(api):
    deal = _create(api)
    # asha is not on the wall
    r = api.call("PATCH", f"/api/deals/{deal['id']}", user="asha",
                 json={"profile": PROFILE})
    assert r.status_code == 404


def test_regulatory_flags_only_still_works(api):
    deal = _create(api, profile=PROFILE)
    r = api.call("PATCH", f"/api/deals/{deal['id']}", json={"regulatory_flags": ["CCI", "FEMA"]})
    assert r.status_code == 200, r.text
    assert r.json()["regulatory_flags"] == ["CCI", "FEMA"]
    assert r.json()["profile"] == PROFILE
    assert _profile_audits(api, deal["id"]) == []
    # compliance still edits flags
    r = api.call("PATCH", f"/api/deals/{deal['id']}", user="priya",
                 json={"regulatory_flags": ["CCI"]})
    assert r.status_code == 200 and r.json()["regulatory_flags"] == ["CCI"]


def test_flags_and_profile_together(api):
    deal = _create(api)
    r = api.call("PATCH", f"/api/deals/{deal['id']}",
                 json={"regulatory_flags": ["CCI"], "profile": PROFILE,
                       "profile_schema_version": 1})
    assert r.status_code == 200, r.text
    assert r.json()["regulatory_flags"] == ["CCI"] and r.json()["profile"] == PROFILE


def test_schema_endpoints(api):
    r = api.call("GET", "/api/deal-profiles/schemas")
    assert r.status_code == 200
    schemas = r.json()
    assert set(schemas) == {"DEBT", "EQUITY", "MNA", "HYBRID", "JV", "LPGP", "ALLIANCE"}
    assert schemas["MNA"]["$id"] == "aura:deal_profile/MNA/v1"

    r = api.call("GET", "/api/deal-profiles/schemas/DEBT", user="priya")
    assert r.status_code == 200
    assert r.json()["x-transaction-class"] == "DEBT"
    assert "facility_type" in r.json()["properties"]

    assert api.call("GET", "/api/deal-profiles/schemas/CRYPTO").status_code == 404
    assert api.client.get("/api/deal-profiles/schemas").status_code == 401
    assert api.client.get("/api/deal-profiles/schemas/DEBT").status_code == 401


def test_backfill_demo_profiles_fills_only_empty_profiles_once(api):
    from aura.data.demo_profiles import DEMO_PROFILES
    from aura.data.seed import backfill_demo_profiles

    empty = api.call("POST", "/api/deals", json={"external_id": "D-001", "name": "Sunrise Infra",
                                                 "transaction_class": "DEBT"}).json()
    edited = api.call("POST", "/api/deals", json={
        "external_id": "D-002", "name": "Ravi Menon Ventures", "transaction_class": "ALLIANCE",
        "profile": {"alliance_type": "licensing"}}).json()
    make_deal(api, "X-9")  # not a demo deal: untouched

    assert backfill_demo_profiles(api.session) == 1
    api.session.commit()
    assert backfill_demo_profiles(api.session) == 0
    api.session.commit()

    deals = {d["external_id"]: d for d in api.call("GET", "/api/deals").json()}
    assert deals["D-001"]["profile"] == DEMO_PROFILES["D-001"]
    assert deals["D-002"]["profile"] == {"alliance_type": "licensing"}
    assert deals["X-9"]["profile"] == {}
    (actor, payload), = _profile_audits(api, empty["id"])
    assert actor == "system" and payload["reason"] == "seed"
    assert payload["changed_keys"] == sorted(DEMO_PROFILES["D-001"])
    assert _profile_audits(api, edited["id"]) == []
