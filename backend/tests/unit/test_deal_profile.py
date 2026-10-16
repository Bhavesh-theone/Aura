import pytest
from jsonschema import Draft202012Validator

from aura.core.domain.enums import Role, TransactionClass
from aura.core.domain.errors import Forbidden, NotFound, RuleViolation
from aura.core.services.deal_profile import (CURRENT_PROFILE_VERSION, SCHEMA_DIR, changed_keys,
                                             get_schema, list_schemas, update_deal_profile,
                                             validate_profile)
from aura.data.demo_profiles import DEMO_PROFILES

C = TransactionClass

SAMPLES = {
    C.DEBT: {"facility_type": "ncd", "amount_inr": 500_000_000, "tenor_months": 36,
             "security_package": {"primary": "Charge on receivables", "security_cover_x": 1.2,
                                  "collateral": ["Pledge of shares"]},
             "covenants": [{"name": "DSCR", "kind": "financial", "threshold": ">= 1.25x",
                            "test_frequency": "annual"}],
             "rating": {"agency": "CRISIL", "grade": "A+", "outlook": "stable",
                        "rated_on": "2026-03-31"}},
    C.EQUITY: {"round_type": "series_b", "instrument": "ccps", "pre_money_inr": 3e9,
               "amount_inr": 6e8, "cap_table_summary": {"promoters_pct": 60, "esop_pct": 8}},
    C.MNA: {"structure": "share_purchase", "stake_pct": 51, "cci_route": "green_channel",
            "enterprise_value_inr": 2_500_000_000, "side": "buy_side"},
    C.HYBRID: {"instrument": "ocd", "amount_inr": 1e8,
               "conversion_terms": {"basis": "fixed_price", "conversion_price_inr": 420,
                                    "trigger": "holder_option"}},
    C.JV: {"partner_country": "JP", "fema_route": "automatic", "press_note_3": False,
           "equity_split": {"client_pct": 74, "partner_pct": 26}},
    C.LPGP: {"fund_category": "venture_capital", "commitment_inr": 1e8,
             "sebi_aif_category": "I"},
    C.ALLIANCE: {"alliance_type": "licensing", "exclusivity": True,
                 "territory": ["Tamil Nadu", "Kerala"], "royalty_pct": 4.5},
}

DEMO_CLASSES = {"D-001": C.DEBT, "D-002": C.ALLIANCE, "AUR-101": C.DEBT, "AUR-102": C.DEBT,
                "AUR-103": C.DEBT, "AUR-104": C.EQUITY, "AUR-105": C.EQUITY,
                "AUR-106": C.MNA, "AUR-107": C.MNA, "AUR-108": C.HYBRID, "AUR-109": C.JV,
                "AUR-110": C.LPGP, "AUR-111": C.ALLIANCE, "AUR-112": C.ALLIANCE,
                "AUR-113": C.ALLIANCE, "AUR-114": C.DEBT, "AUR-115": C.MNA,
                "AUR-116": C.DEBT, "AUR-117": C.ALLIANCE}


@pytest.mark.parametrize("cls", list(C))
def test_each_schema_is_a_valid_2020_12_schema(cls):
    schema = get_schema(cls)
    Draft202012Validator.check_schema(schema)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["$id"] == f"aura:deal_profile/{cls.value}/v1"
    assert schema["x-transaction-class"] == cls.value
    assert schema["x-schema-version"] == CURRENT_PROFILE_VERSION == 1
    assert schema["additionalProperties"] is False
    assert (SCHEMA_DIR / f"{cls.value}.v1.json").is_file()


def test_list_schemas_has_every_class_and_returns_copies():
    schemas = list_schemas()
    assert set(schemas) == {c.value for c in C}
    schemas["DEBT"]["title"] = "mutated"
    assert get_schema("DEBT")["title"] != "mutated"


@pytest.mark.parametrize("cls", list(C))
def test_empty_profile_and_sample_validate(cls):
    validate_profile(cls, 1, {})
    validate_profile(cls, None, SAMPLES[cls])


def test_every_demo_profile_validates():
    assert set(DEMO_PROFILES) == set(DEMO_CLASSES)
    for ext, profile in DEMO_PROFILES.items():
        validate_profile(DEMO_CLASSES[ext], 1, profile)


@pytest.mark.parametrize("cls, profile, needle", [
    (C.DEBT, {"tenor_months": "84"}, "profile.tenor_months"),
    (C.DEBT, {"amount_inr": -1}, "profile.amount_inr"),
    (C.DEBT, {"facility_type": "payday"}, "profile.facility_type"),
    (C.DEBT, {"rating": {"agency": "Moody's", "grade": "A"}}, "profile.rating.agency"),
    (C.DEBT, {"covenants": [{"kind": "financial"}]}, "profile.covenants[0]"),
    (C.DEBT, {"rating": {"agency": "CRISIL", "grade": "A", "rated_on": "31/03/2026"}},
     "profile.rating.rated_on"),
    (C.MNA, {"stake_pct": 101}, "profile.stake_pct"),
    (C.MNA, {"stake_pct": -5}, "profile.stake_pct"),
    (C.EQUITY, {"pre_money_inr": -100}, "profile.pre_money_inr"),
    (C.JV, {"press_note_3": "yes"}, "profile.press_note_3"),
    (C.JV, {"partner_country": "Germany"}, "profile.partner_country"),
    (C.LPGP, {"sebi_aif_category": "IV"}, "profile.sebi_aif_category"),
    (C.ALLIANCE, {"unknown_key": 1}, "unknown_key"),
    (C.EQUITY, {"cap_table_summary": {"founders": 50}}, "founders"),
    (C.HYBRID, {"stake_pct": 10}, "stake_pct"),  # another class's field
])
def test_invalid_profiles_are_rule_violations(cls, profile, needle):
    with pytest.raises(RuleViolation) as exc:
        validate_profile(cls, 1, profile)
    assert needle in str(exc.value)


def test_non_object_and_unknown_version_are_rule_violations():
    with pytest.raises(RuleViolation, match="JSON object"):
        validate_profile(C.DEBT, 1, ["not", "a", "dict"])
    with pytest.raises(RuleViolation, match="version 2"):
        validate_profile(C.DEBT, 2, {})


def test_unknown_class_or_version_schema_is_not_found():
    with pytest.raises(NotFound):
        get_schema("CRYPTO")
    with pytest.raises(NotFound):
        get_schema(C.DEBT, 99)


def test_changed_keys():
    assert changed_keys({"a": 1, "b": 2, "c": 3}, {"a": 1, "b": 5, "d": 0}) == ["b", "c", "d"]
    assert changed_keys({}, {}) == []


class _Deals:
    def __init__(self, deal):
        self.deal = deal

    def get(self, deal_id):
        return self.deal if self.deal and self.deal.id == deal_id else None

    def update(self, deal):
        self.deal = deal
        return deal


class _Audit:
    def __init__(self):
        self.entries = []

    def append(self, entry):
        self.entries.append(entry)
        return entry


def _deal():
    from datetime import datetime, timezone

    from aura.core.domain.deal import Deal
    from aura.core.domain.enums import DealStage
    return Deal(id=7, external_id="X-1", name="X", stage=DealStage.ORIGINATED,
                transaction_class=C.MNA, owner="bhavesh", outcome=None,
                opened_at=datetime.now(timezone.utc), profile={"stake_pct": 26})


def test_update_deal_profile_rules():
    deals, audit = _Deals(_deal()), _Audit()
    saved = update_deal_profile(7, {"stake_pct": 51, "cci_route": "form_i"}, "asha",
                                Role.ANALYST, deals, audit)
    assert saved.profile == {"stake_pct": 51, "cci_route": "form_i"}
    entry = audit.entries[-1]
    assert entry.action == "deal_profile_updated" and entry.deal_id == 7
    assert entry.payload == {"profile_schema_version": 1,
                             "changed_keys": ["cci_route", "stake_pct"]}
    with pytest.raises(Forbidden):
        update_deal_profile(7, {}, "priya", Role.COMPLIANCE, deals, audit)
    with pytest.raises(Forbidden):
        update_deal_profile(7, {}, "admin", Role.ADMIN, deals, audit)
    with pytest.raises(NotFound):
        update_deal_profile(8, {}, "asha", Role.ANALYST, deals, audit)
    with pytest.raises(RuleViolation):
        update_deal_profile(7, {"stake_pct": 150}, "bhavesh", Role.DEALMAKER, deals, audit)
    assert deals.deal.profile["stake_pct"] == 51 and len(audit.entries) == 1
