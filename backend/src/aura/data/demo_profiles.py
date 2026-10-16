"""Deal profiles (class-specific terms) for every demo deal, keyed by external_id.

Used by seed (D-001, D-002) and the demo stories (AUR-101 ... AUR-117) when they create a
deal, and by seed.backfill_demo_profiles for demo deals created before profiles existed.
Every profile validates against its class's current schema (tests check this)."""
import copy

CR = 10_000_000  # one crore, in rupees

DEMO_PROFILES: dict[str, dict] = {
    # ------------------------------------------------------------------ seed deals
    "D-001": {  # Sunrise Infra, DEBT
        "facility_type": "term_loan", "amount_inr": 60 * CR, "tenor_months": 84,
        "moratorium_months": 12, "repayment": "ballooning", "rate_type": "floating",
        "benchmark": "mclr", "interest_rate_pct": 10.25,
        "security_package": {"primary": "First charge on project assets and receivables",
                             "collateral": ["Pledge of 51% promoter shareholding"],
                             "security_cover_x": 1.33, "personal_guarantee": True,
                             "ranking": "first_pari_passu"},
        "covenants": [{"name": "DSCR", "kind": "financial", "threshold": ">= 1.20x",
                       "test_frequency": "annual"},
                      {"name": "Total debt / EBITDA", "kind": "financial",
                       "threshold": "<= 4.0x", "test_frequency": "annual"}],
        "rating": {"agency": "CARE", "grade": "BBB+", "outlook": "stable"},
        "lenders_targeted": 6, "end_use": "Capex for road maintenance equipment"},
    "D-002": {  # Ravi Menon Ventures, ALLIANCE
        "alliance_type": "co_marketing", "exclusivity": False,
        "territory": ["Kerala", "Karnataka"], "term_months": 24,
        "revenue_share_pct": 15, "renewal": "mutual"},

    # ------------------------------------------------------------------ demo stories
    "AUR-101": {  # Saurashtra Spinning Mills, DEBT, Rs 40 Cr working capital
        "facility_type": "working_capital", "amount_inr": 40 * CR, "tenor_months": 12,
        "repayment": "on_demand", "rate_type": "floating", "benchmark": "eblr",
        "interest_rate_pct": 9.6,
        "security_package": {"primary": "Hypothecation of stocks and book debts",
                             "collateral": ["Equitable mortgage of Rajkot spinning unit"],
                             "security_cover_x": 1.4, "personal_guarantee": True,
                             "ranking": "first_pari_passu"},
        "covenants": [{"name": "Current ratio", "kind": "financial", "threshold": ">= 1.33x",
                       "test_frequency": "half_yearly"},
                      {"name": "Monthly stock statements", "kind": "information"}],
        "rating": {"agency": "CRISIL", "grade": "BBB", "outlook": "stable"},
        "lenders_targeted": 2, "end_use": "Cotton procurement in the peak season"},
    "AUR-102": {  # Panchal Ceramica (Morbi), DEBT, Rs 85 Cr senior secured term loan
        "facility_type": "term_loan", "amount_inr": 85 * CR, "tenor_months": 72,
        "moratorium_months": 12, "repayment": "equated", "rate_type": "floating",
        "benchmark": "mclr", "interest_rate_pct": 9.85,
        "security_package": {"primary": "First charge on fixed assets of the Morbi plant",
                             "collateral": ["Second charge on current assets"],
                             "security_cover_x": 1.5, "personal_guarantee": True,
                             "corporate_guarantee": False, "ranking": "first_pari_passu"},
        "covenants": [{"name": "DSCR", "kind": "financial", "threshold": ">= 1.25x",
                       "test_frequency": "annual"},
                      {"name": "Net debt / EBITDA", "kind": "financial",
                       "threshold": "<= 3.0x", "test_frequency": "annual"},
                      {"name": "No further borrowing without consent", "kind": "negative"}],
        "rating": {"agency": "ICRA", "grade": "A-", "outlook": "stable"},
        "lenders_targeted": 4, "end_use": "Kiln capacity expansion and gas-fired dryers"},
    "AUR-103": {  # Tungabhadra Fincorp, DEBT, Rs 15 Cr term loan to an NBFC
        "facility_type": "term_loan", "amount_inr": 15 * CR, "tenor_months": 36,
        "repayment": "equated", "rate_type": "fixed", "interest_rate_pct": 11.5,
        "security_package": {"primary": "Exclusive charge on standard loan receivables",
                             "security_cover_x": 1.1, "ranking": "exclusive"},
        "covenants": [{"name": "Capital adequacy", "kind": "financial",
                       "threshold": ">= 18%", "test_frequency": "quarterly"},
                      {"name": "GNPA", "kind": "financial", "threshold": "<= 4%",
                       "test_frequency": "quarterly"}],
        "rating": {"agency": "India Ratings", "grade": "BBB-", "outlook": "positive"},
        "lenders_targeted": 3, "end_use": "On-lending to MSME borrowers"},
    "AUR-104": {  # Shivneri Cloud Systems, EQUITY, Rs 120 Cr Series C
        "round_type": "series_c", "instrument": "ccps", "amount_inr": 120 * CR,
        "primary_inr": 100 * CR, "secondary_inr": 20 * CR, "pre_money_inr": 780 * CR,
        "post_money_inr": 880 * CR,
        "cap_table_summary": {"promoters_pct": 46.5, "investors_pct": 41.0,
                              "esop_pct": 10.0, "others_pct": 2.5},
        "board_seats": 1, "liquidation_preference": "1x_non_participating",
        "anti_dilution": "broad_based_weighted_average"},
    "AUR-105": {  # Malabar Spice & Condiments, EQUITY, pre-IPO secondary
        "round_type": "pre_ipo", "instrument": "equity", "amount_inr": 45 * CR,
        "primary_inr": 0, "secondary_inr": 45 * CR, "pre_money_inr": 620 * CR,
        "cap_table_summary": {"promoters_pct": 72.0, "investors_pct": 18.0,
                              "esop_pct": 3.0, "others_pct": 7.0},
        "board_seats": 0, "liquidation_preference": "none", "anti_dilution": "none"},
    "AUR-106": {  # Ankleshwar Organics, MNA, division carve-out (sell side)
        "structure": "slump_sale", "side": "sell_side", "stake_pct": 100,
        "enterprise_value_inr": 210 * CR, "ev_ebitda_multiple": 8.5,
        "consideration": "cash", "cci_route": "not_notifiable", "target_listed": False,
        "nclt_approval": False, "target_sector": "Agro-chemical intermediates"},
    "AUR-107": {  # Pranhita Steel Re-Rollers, MNA, IBC resolution plan (buy side)
        "structure": "ibc_resolution_plan", "side": "buy_side", "stake_pct": 100,
        "enterprise_value_inr": 145 * CR, "consideration": "deferred",
        "cci_route": "green_channel", "target_listed": False, "nclt_approval": True,
        "target_sector": "Steel re-rolling"},
    "AUR-108": {  # Deccan Agro Foods, HYBRID, Rs 30 Cr CCD round
        "instrument": "ccd", "amount_inr": 30 * CR, "coupon_pct": 0.01, "tenor_months": 36,
        "conversion_terms": {"basis": "valuation_cap", "valuation_cap_inr": 400 * CR,
                             "discount_pct": 20, "trigger": "next_round",
                             "long_stop_months": 36},
        "fema_pricing_compliant": True},
    "AUR-109": {  # Satpura Motion Controls x Rheintal, JV, servo drives
        "partner_name": "Rheintal Antriebstechnik GmbH", "partner_country": "DE",
        "fema_route": "automatic", "press_note_3": False,
        "equity_split": {"client_pct": 51, "partner_pct": 49}, "vehicle": "private_limited",
        "initial_capital_inr": 35 * CR, "sector": "Industrial servo drives",
        "technology_licence": True, "deadlock_mechanism": "escalation"},
    "AUR-110": {  # Nilgiri Family Office, LPGP, Rs 25 Cr LP commitment
        "fund_name": "Western Ghats Growth Fund II", "side": "lp",
        "fund_category": "private_equity", "sebi_aif_category": "II",
        "commitment_inr": 25 * CR, "target_corpus_inr": 1200 * CR,
        "management_fee_pct": 2.0, "carry_pct": 20, "hurdle_pct": 10,
        "fund_term_years": 8, "gift_city": False},
    "AUR-111": {  # Noyyal Knit Exports, ALLIANCE, North-East distribution
        "alliance_type": "distribution", "exclusivity": True,
        "territory": ["Assam", "Meghalaya", "Tripura", "Nagaland"], "term_months": 36,
        "minimum_commitment_inr": 6 * CR, "renewal": "mutual"},
    "AUR-112": {  # Sabarmati Packaging, ALLIANCE, supply exclusivity with Kalinga Consumer
        "alliance_type": "supply", "exclusivity": True, "territory": ["Odisha", "West Bengal"],
        "term_months": 48, "minimum_commitment_inr": 18 * CR, "renewal": "automatic"},
    "AUR-113": {  # Kutch Marine Salts, ALLIANCE, co-marketing
        "alliance_type": "co_marketing", "exclusivity": False,
        "territory": ["Gujarat", "Maharashtra", "Rajasthan"], "term_months": 24,
        "revenue_share_pct": 12, "renewal": "mutual"},
    "AUR-114": {  # Chambal Agro Warehousing, DEBT, Rs 22 Cr warehouse receipt line
        "facility_type": "warehouse_receipt_finance", "amount_inr": 22 * CR,
        "tenor_months": 12, "repayment": "bullet", "rate_type": "floating",
        "benchmark": "repo", "interest_rate_pct": 9.25,
        "security_package": {"primary": "Pledge of WDRA-negotiable warehouse receipts",
                             "security_cover_x": 1.43, "ranking": "exclusive"},
        "covenants": [{"name": "Margin on receipts", "kind": "financial",
                       "threshold": ">= 30%", "test_frequency": "quarterly"}],
        "rating": {"agency": "Acuite", "grade": "BBB-", "outlook": "stable"},
        "end_use": "Post-harvest finance for mustard and wheat stocks"},
    "AUR-115": {  # Chilika Aqua Exports, MNA, buy-side acquisition of a shrimp processor
        "structure": "share_purchase", "side": "buy_side", "stake_pct": 76,
        "enterprise_value_inr": 95 * CR, "equity_value_inr": 58 * CR,
        "ev_ebitda_multiple": 7.0, "consideration": "mixed", "cci_route": "not_notifiable",
        "target_listed": False, "open_offer_triggered": False,
        "target_sector": "Shrimp processing and export"},
    "AUR-116": {  # Bundelkhand Solar Parks, DEBT, Rs 180 Cr project finance
        "facility_type": "project_finance", "amount_inr": 180 * CR, "tenor_months": 216,
        "moratorium_months": 18, "repayment": "structured", "rate_type": "floating",
        "benchmark": "mclr", "interest_rate_pct": 9.1,
        "security_package": {"primary": "First charge on project assets and PPA receivables",
                             "collateral": ["Pledge of 51% sponsor shares",
                                            "Escrow of DISCOM payments"],
                             "security_cover_x": 1.25, "corporate_guarantee": True,
                             "ranking": "first_pari_passu"},
        "covenants": [{"name": "DSCR", "kind": "financial", "threshold": ">= 1.30x",
                       "test_frequency": "annual"},
                      {"name": "DSRA of two quarters", "kind": "affirmative"}],
        "rating": {"agency": "CRISIL", "grade": "A", "outlook": "stable"},
        "lenders_targeted": 5, "end_use": "120 MW solar park construction"},
    "AUR-117": {  # Konkan Coastal Logistics, ALLIANCE, cold-chain alliance
        "alliance_type": "technology", "exclusivity": False,
        "territory": ["Maharashtra", "Goa", "Coastal Karnataka"], "term_months": 60,
        "revenue_share_pct": 8, "renewal": "automatic"},
}


def demo_profile(external_id: str) -> dict | None:
    """A copy of the demo profile for a deal, or None if it is not a demo deal."""
    profile = DEMO_PROFILES.get(external_id)
    return copy.deepcopy(profile) if profile is not None else None
