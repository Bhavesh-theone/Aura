"""Demo dataset: a realistic, fictional Indian mid-market deal desk.

    uv run python -m aura.data.demo [--with-agents] [--db DATABASE]

Opt-in and idempotent. Every record is created through the real core services, acting as
the user who would do it (dealmakers move deals, analysts upload and work diligence,
compliance staffs walls and signs off), so stage history, guard evaluations, walls, the
audit hash chain and the metrics are the real thing. The only thing simulated is time: a
replay clock (aura.core.clock.use_clock) walks the last ~6 months of business days and the
events of all deals run in one chronological order.

Agent work runs through the stub orchestrator (recorded honestly as model 'stub'). With
--with-agents two of the jobs run on the live CrewAI + Ollama crew instead.

Deals are keyed by external_id (AUR-101 ... AUR-117) and users by username: a re-run adds
nothing, and deals that are not the demo's (D-001, D-002, ...) are never touched.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone

HORIZON_DAYS = 126  # business days, about six calendar months


def inr(n: int) -> str:
    """Indian digit grouping: 312400000 -> 3,12,40,00,000."""
    if n < 0:
        return "-" + inr(-n)
    s = str(n)
    if len(s) <= 3:
        return s
    head, tail = s[:-3], s[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return ",".join(groups) + "," + tail


def fin_lines(name: str, fy: str, revenue: int, ebitda: int, net_debt: int) -> list[str]:
    return [f"{name} - audited statement of profit and loss, {fy}",
            "All figures in INR",
            f"Revenue from operations: {inr(revenue)}",
            f"EBITDA: {inr(ebitda)}",
            f"Net debt: {inr(net_debt)}",
            "Auditor: unmodified opinion"]


def package(question: str, options: list[tuple[str, str, str, bool]], recommendation: str,
            confidence: float, rationale: str, what_happened: list[str], evidence: list,
            consequence: str, escalate_at: datetime, dissent: str | None = None,
            escalates_to_role: str = "dealmaker") -> dict:
    decision = {"question": question,
                "options": [{"id": i, "label": label, "consequence": c, "reversible": rev}
                            for i, label, c, rev in options],
                "recommendation": recommendation, "confidence": confidence,
                "rationale": rationale}
    if dissent:
        decision["dissent"] = dissent
    return {"decision_required": decision, "what_happened": what_happened,
            "evidence": evidence,
            "if_you_do_nothing": {"consequence": consequence,
                                  "auto_escalate_at": escalate_at.isoformat(),
                                  "escalates_to_role": escalates_to_role}}


def build(desk, days, run_now: datetime):
    """All demo stories. Returns them in definition order."""
    from aura.core.domain.enums import (DealStage as S, DocClass as D, FindingType as F,
                                        HandoffTrigger as T, MandateSide as M,
                                        PartyRole as R, TransactionClass as C)
    from aura.data.demo_story import Story, crit

    stories: list[Story] = []

    def story(*a, **k) -> Story:
        st = Story(desk, days, *a, **k)
        stories.append(st)
        return st

    def later(hours: float) -> datetime:
        return run_now + timedelta(hours=hours)

    # ---------------------------------------------------------------- AUR-111 ALLIANCE won
    s = story("AUR-111", "Noyyal Knit Exports — North-East distribution alliance",
              C.ALLIANCE, "neha", "asha", "noyyal", R.SELLER,
              [("brahmaputra", R.BUYER), ("vidarbha", R.BUYER)], counsel="sindhu_law")
    s.create(0)
    s.staff(0, add=["bhavesh", "asha"])
    s.job(16, "email", lambda s=s: {"capability": "draft_email",
                                    "party_id": s.party_ids["brahmaputra"],
                                    "brief": "Share the alliance term summary and propose a "
                                             "call on minimum purchase commitments."})
    s.resolve(16, "email", ["reject"],
              "Tone is too familiar for a first written approach and it quotes the minimum "
              "purchase number before Noyyal has approved it. I will write this one myself.",
              "Neha sends the first written approach", "No reply from Brahmaputra in 5 days",
              by="neha")
    s.walk([(2, S.QUALIFIED), (4, S.MANDATED), (6, S.PREPARED), (9, S.MARKETED),
            (14, S.MATCHED), (19, S.BID_AUCTION), (23, S.NEGOTIATION), (27, S.DILIGENCE),
            (35, S.DOCUMENTATION), (41, S.CONDITIONS_PRECEDENT)],
           mandate=("Exclusive distribution partner for the North-East", M.PARTNER,
                    [crit("territory", "in", ["Assam", "Meghalaya", "Tripura", "Arunachal "
                                              "Pradesh"]),
                     crit("minimum_annual_purchase_inr", "gte", 180000000),
                     crit("retail_doors", "gte", 400, "soft", 0.6),
                     crit("exclusivity_months", "between", [24, 36]),
                     crit("credit_terms_days", "lte", 45, "preference")],
                    "Noyyal wants one distributor for its own-brand knitwear in the "
                    "North-East; buyer-side exclusivity in return for a purchase floor."),
           financials=[("fs", "FY26 Audited Financial Statements - Noyyal Knit Exports.pdf",
                        D.FINANCIAL_STATEMENT,
                        fin_lines("Noyyal Knit Exports Pvt Ltd", "FY 2025-26", 2184000000,
                                  246000000, 412000000))],
           valuation=("Partner Economics and Channel Valuation - Noyyal alliance.pdf",
                      ["Five-year channel P&L for the North-East territory",
                       "NPV of the alliance to Noyyal at 14% WACC: INR 38.6 Cr"], False),
           term_sheet=("Alliance Term Sheet - Brahmaputra Retail - signed.pdf",
                       ["Exclusive distribution, 30 months",
                        "Minimum annual purchase INR 21 Cr, bank guarantee INR 2.5 Cr"]),
           definitive=("Distribution and Brand Licence Agreement - Brahmaputra Retail - "
                       "executed.pdf", D.TERM_SHEET,
                       ["Definitive distribution and brand licence agreement",
                        "Executed by both parties"]),
           overrides={S.CONDITIONS_PRECEDENT: lambda s=s: (
               f"Alliance: the definitive document is the distribution and brand licence "
               f"agreement (document #{s.docs['definitive']}, executed). T10 only "
               f"recognises an SPA or SHPA, which an alliance does not have.")})
    s.standard_diligence(28, 33)
    s.cp(41, "tm", "Recordal of the trademark licence with the Trade Marks Registry (Form "
         "TM-P)", "regulatory")
    s.cp(41, "bg", "Bank guarantee of INR 2.5 Cr for the minimum purchase commitment "
         "delivered", "commercial", hhmm="15:05")
    s.cp(41, "board", "Board approvals of both parties", "corporate", hhmm="15:10")
    s.cp_set(43, "board", "satisfied")
    s.cp_set(46, "bg", "satisfied")
    s.cp_set(47, "tm", "in_progress")
    s.move(49, S.CLOSED, by="priya", hhmm="17:00", override=(
        "TM-P recordal is a post-closing filing; it does not affect enforceability between "
        "the parties and the licence is effective on signing. Tracked as a post-closing "
        "undertaking with a 30-day deadline."))

    # ---------------------------------------------------------------- AUR-101 DEBT won
    s = story("AUR-101", "Saurashtra Spinning Mills — ₹40 Cr working capital",
              C.DEBT, "vikram", "asha", "saurashtra", R.ISSUER,
              [("narmada", R.LENDER), ("ujjayini", R.LENDER)], counsel="desai_mehta")
    s.create(3)
    s.staff(3, add=["bhavesh", "asha", "rohan"])
    s.walk([(5, S.QUALIFIED), (8, S.MANDATED), (10, S.PREPARED), (13, S.MARKETED),
            (17, S.MATCHED), (20, S.BID_AUCTION), (24, S.NEGOTIATION), (29, S.DILIGENCE),
            (38, S.DOCUMENTATION), (44, S.CONDITIONS_PRECEDENT)],
           mandate=("Raise ₹40 Cr fund-based working capital", M.RAISE,
                    [crit("facility_amount_inr", "between", [350000000, 450000000]),
                     crit("tenor_months", "lte", 12),
                     crit("security", "contains", "first charge on current assets"),
                     crit("spread_over_repo_bps", "lte", 325, "soft", 0.6),
                     crit("lender_type", "in", ["small finance bank", "credit fund"],
                          "preference")],
                    "Cotton price spike has stretched the cycle; renewal of the existing "
                    "₹28 Cr CC limit plus ₹12 Cr enhancement."),
           financials=[("fs", "FY26 Audited Financial Statements - Saurashtra Spinning.pdf",
                        D.FINANCIAL_STATEMENT,
                        fin_lines("Saurashtra Spinning Mills Pvt Ltd", "FY 2025-26",
                                  3124000000, 341000000, 612000000))],
           valuation=("Credit Appraisal and Collateral Valuation - Saurashtra Spinning.pdf",
                      ["Drawing power on stock and book debts: INR 46.2 Cr",
                       "DSCR 1.62x, current ratio 1.31x"], False),
           term_sheet=("Sanction Letter and Term Sheet - Ujjayini SFB - accepted.pdf",
                       ["Cash credit INR 40 Cr, 12 months renewable",
                        "Repo + 290 bps, first pari passu charge on current assets"]),
           definitive=("Working Capital Facility Agreement and Deed of Hypothecation - "
                       "Ujjayini SFB - executed.pdf", D.CHARGE_DOCUMENT,
                       ["Facility agreement and deed of hypothecation",
                        "Executed by the borrower and the lender"]),
           overrides={S.CONDITIONS_PRECEDENT: lambda s=s: (
               f"Debt deal: the definitive documents are the facility agreement and deed of "
               f"hypothecation (document #{s.docs['definitive']}, executed). T10 only "
               f"recognises an SPA or SHPA.")})
    s.job(13, "classify", lambda s=s: {"capability": "classify_document",
                                       "document_id": s.docs["fs"]}, hhmm="17:40")
    s.resolve(14, "classify", ["confirm"],
              "Audited financials for FY26 with an unmodified opinion; the class is right.",
              "Lender data room opens", "Class disputed by a lender", by="vikram",
              hhmm="09:40")
    s.job(18, "email", lambda s=s: {"capability": "draft_email",
                                    "party_id": s.party_ids["narmada"],
                                    "brief": "Send the credit note summary and ask for "
                                             "indicative terms by Friday."}, by="rohan")
    s.resolve(18, "email", ["approve"],
              "Draft is accurate and does not quote pricing; fine to send from my mailbox "
              "after I add the data-room link.",
              "Narmada returns indicative terms", "No indicative terms within 7 days",
              by="vikram")
    s.standard_diligence(30, 36)
    s.cp(44, "chg1", "Creation of charge and filing of Form CHG-1 with the ROC",
         "regulatory")
    s.cp(44, "board", "Borrower board resolution under section 179(3)", "corporate",
         hhmm="15:05")
    s.cp(44, "insurance", "Stock insurance with the lender endorsed as loss payee",
         "commercial", hhmm="15:10")
    s.cp(44, "stock_audit", "Stock audit by a lender-appointed auditor", "commercial",
         hhmm="15:15")
    s.cp_set(46, "board", "satisfied")
    s.cp_set(48, "insurance", "satisfied")
    s.cp_set(50, "chg1", "satisfied")
    s.cp_set(51, "stock_audit", "waived", waiver=(
        "Lender accepted the September consortium stock audit (dated within 60 days) in "
        "place of a fresh audit."))
    s.move(52, S.CLOSED, hhmm="17:00")

    # ---------------------------------------------------------------- AUR-107 MNA aborted
    s = story("AUR-107", "Pranhita Steel Re-Rollers — IBC resolution plan", C.MNA, "vikram",
              "rohan", "gondwana", R.BUYER, [("vindhya", R.INVESTOR), ("narmada", R.LENDER)])
    s.create(8)
    s.staff(8, add=["bhavesh", "rohan"], remove=["meera"])
    s.party(10, "pranhita", R.TARGET, hhmm="10:35")
    s.walk([(10, S.QUALIFIED), (13, S.MANDATED), (16, S.PREPARED), (21, S.MARKETED),
            (27, S.MATCHED), (33, S.BID_AUCTION), (40, S.NEGOTIATION), (47, S.DILIGENCE)],
           mandate=("Acquire Pranhita Steel through a CIRP resolution plan", M.BUY,
                    [crit("plan_value_inr", "lte", 650000000),
                     crit("capacity_tpa", "gte", 120000),
                     crit("upfront_cash_pct", "gte", 40, "soft", 0.5),
                     crit("location", "in", ["Telangana", "Andhra Pradesh"], "preference")],
                    "Gondwana wants a rolling mill near its billet plant; ceiling set by "
                    "its board at ₹65 Cr all-in."),
           financials=[("fs", "Information Memorandum and FY25 Financials - Pranhita "
                        "Steel.pdf", D.FINANCIAL_STATEMENT,
                        fin_lines("Pranhita Steel Re-Rollers Pvt Ltd", "FY 2024-25",
                                  1460000000, -84000000, 2310000000))],
           valuation=("Fair Value and Liquidation Value Report - Pranhita Steel.pdf",
                      ["Fair value INR 74.8 Cr; liquidation value INR 51.2 Cr",
                       "Prepared by a registered valuer for the RP"], False),
           term_sheet=("Plan Funding Term Sheet - Vindhya Capital - signed.pdf",
                       ["Equity INR 25 Cr, acquisition debt INR 40 Cr"]))
    s.standard_diligence(48, 54, skip=("litigation",))
    s.doc(48, "litigation", "Claims Register and Avoidance Applications - Pranhita "
          "Steel.pdf", D.LITIGATION_SUMMARY,
          ["Claims admitted by the RP: INR 231 Cr", "Section 66 application pending"])
    s.dd(48, "litigation", "requested", hhmm="10:10")
    s.dd(52, "litigation", "under_review", ["litigation"])
    s.finding(55, "litigation", F.RED_FLAG,
              "Operational creditor claims of ₹11.2 Cr rejected by the RP are being "
              "challenged before the NCLT; if admitted, the plan must absorb them.",
              112000000, True)
    s.dd(56, "litigation", "failed", hhmm="11:20")
    s.brief(57, "raise_bid", "plan_revision", T.MATERIALITY_GATE, lambda now, s=s: package(
        "Should Gondwana raise its resolution plan from ₹62 Cr to ₹71 Cr to stay "
        "ahead of the competing applicant?",
        [("raise", "Raise to ₹71 Cr", "Exceeds the ₹65 Cr board ceiling; needs a "
          "fresh board approval and more acquisition debt.", False),
         ("hold", "Hold at ₹62 Cr", "Plan may lose the CoC vote; the deal could lapse.",
          True),
         ("reject", "Withdraw from the process", "Gondwana exits; costs to date (about "
          "₹1.4 Cr) are sunk.", False)],
        "hold", 0.62,
        "The ₹11.2 Cr contested claim makes the real price ₹73 Cr+ if we raise.",
        ["CoC indicated the competing plan is at about ₹68 Cr.",
         "Diligence found ₹11.2 Cr of contested operational claims."],
        [s.ev("litigation", "claims register"), s.ev("valuation", "fair value ₹74.8 Cr")],
        "The plan stays at ₹62 Cr and the CoC votes on the existing offers.",
        now + timedelta(hours=24),
        dissent="Rohan: the liquidation value floor makes ₹71 Cr defensible."),
        620000000)
    s.resolve(58, "raise_bid", ["reject"],
              "Board will not go above ₹65 Cr and the contested claims push the real "
              "price beyond it. Better to walk now than win at the wrong price.",
              "CoC vote outcome", "CoC asks for a revised plan", by="vikram")
    s.move(63, S.ABORTED, reason="coc_rejected_resolution_plan", hhmm="18:10")

    # ---------------------------------------------------------------- AUR-106 MNA carve-out
    s = story("AUR-106", "Ankleshwar Organics — agro-intermediates division carve-out",
              C.MNA, "bhavesh", "asha", "ankleshwar", R.SELLER,
              [("bharuch", R.BUYER), ("vapi", R.BUYER)], counsel="sindhu_law")
    s.create(10)
    s.staff(10, add=["asha", "kavya"])
    s.walk([(12, S.QUALIFIED), (15, S.MANDATED), (18, S.PREPARED), (24, S.MARKETED),
            (31, S.MATCHED), (38, S.BID_AUCTION), (50, S.NEGOTIATION), (64, S.DILIGENCE),
            (84, S.DOCUMENTATION)],
           mandate=("Sell the agro-intermediates division as a going concern", M.SELL,
                    [crit("enterprise_value_inr", "gte", 2400000000),
                     crit("structure", "eq", "slump sale"),
                     crit("employee_transfer_pct", "gte", 95, "soft", 0.7),
                     crit("buyer_type", "in", ["strategic"], "preference")],
                    "Listed seller exiting a non-core division (Jhagadia unit, 3 product "
                    "lines). Board wants the deal signed before the March results."),
           financials=[("fs", "Carve-out Financials FY24-FY26 - Agro-Intermediates "
                        "Division.pdf", D.FINANCIAL_STATEMENT,
                        fin_lines("Agro-intermediates division of Ankleshwar Organics Ltd",
                                  "FY 2025-26", 3460000000, 512000000, 0))],
           valuation=("Business Valuation - Agro-Intermediates Division - Ankleshwar "
                      "Organics.pdf", ["EV range INR 252-281 Cr (DCF, EV/EBITDA 5.2x)",
                                       "Contains unpublished price-sensitive information"],
                      True),
           term_sheet=("Binding Term Sheet - Bharuch Fine Chemicals - signed.pdf",
                       ["Slump sale at INR 268 Cr EV, working capital peg INR 41 Cr"]))
    s.flags(52, ["CCI: combination notice (Form I) under section 6(2)"])
    s.brief(56, "cci_route", "regulatory_route", T.POLICY_REQUIRED, lambda now, s=s: package(
        "Which CCI filing route should the parties use for the carve-out?",
        [("green_channel", "Green Channel", "Deemed approval on filing, but a wrong "
          "self-assessment voids the approval.", False),
         ("form_i", "Regular Form I", "About 30 working days to approval; becomes a "
          "condition precedent to closing.", True)],
        "form_i", 0.86,
        "Bharuch already sells two overlapping intermediates; Green Channel needs no "
        "horizontal overlap.",
        ["Buyer and target overlap in two of three product lines."],
        [s.ev("valuation", "division EV and product mix")],
        "The SPA long-stop date cannot be set and signing slips.", now + timedelta(hours=24),
        escalates_to_role="compliance"), None)
    s.resolve(57, "cci_route", ["form_i"],
              "Overlap in two product lines rules out Green Channel. File Form I after "
              "signing and make CCI approval a CP.",
              "Form I filed", "CCI raises a request for information", by="priya")
    s.job(66, "classify", lambda s=s: {"capability": "classify_document",
                                       "document_id": s.docs["valuation"]}, hhmm="12:10")
    s.resolve(66, "classify", ["confirm"],
              "Valuation report correctly classed. The data room index is settled, so do not "
              "ask again on this deal.",
              "Data room index frozen", "A new document type appears",
              do_not_revisit=["classify_document"], hhmm="18:00")
    s.standard_diligence(65, 76)
    s.doc(67, "cto", "Consent to Operate - GPCB - Jhagadia unit.pdf", D.ENV_CLEARANCE,
          ["Consent to operate under the Water and Air Acts", "Valid until 31 Jan 2027"])
    s.job(70, "classify2", lambda s=s: {"capability": "classify_document",
                                        "document_id": s.docs["cto"]})
    s.finding(73, "audited financial", F.ADJUSTMENT,
              "Working capital at signing is ₹8.6 Cr below the normalised peg of "
              "₹41 Cr; price adjusts rupee for rupee.", 86000000, True)
    s.finding(74, "incorporation", F.OBSERVATION,
              "GPCB consent to operate for the Jhagadia unit expires in January 2027; the "
              "renewal application must be transferred to the buyer.", None, False)
    s.signoff(82, "Reviewed the CCI combination analysis: Form I after signing, approval a "
              "CP to closing. No SEBI LODR issue beyond the outcome disclosure.")
    s.doc(90, "bta", "Business Transfer Agreement (slump sale) - draft v3 - Ankleshwar "
          "Organics.pdf", D.SPA, ["Draft v3 marked up by buyer's counsel",
                                  "Open points: indemnity cap, employee transfer"],
          sensitivity=4, upsi=True)

    # ---------------------------------------------------------------- AUR-112 ALLIANCE lapsed
    s = story("AUR-112", "Sabarmati Packaging — supply exclusivity with Kalinga Consumer",
              C.ALLIANCE, "vikram", "rohan", "sabarmati", R.SELLER, [("kalinga", R.BUYER)])
    s.create(15)
    s.staff(15, add=["rohan"], remove=["meera"])
    s.walk([(17, S.QUALIFIED), (21, S.MANDATED), (24, S.PREPARED), (30, S.MARKETED),
            (38, S.MATCHED)],
           mandate=("Three-year exclusive corrugated supply to one FMCG", M.PARTNER,
                    [crit("annual_volume_tonnes", "gte", 18000),
                     crit("price_reset", "eq", "quarterly, kraft paper index"),
                     crit("payment_terms_days", "lte", 60, "soft", 0.5)],
                    "Sabarmati wants volume certainty for its new corrugator line."),
           financials=[("fs", "FY26 Audited Financial Statements - Sabarmati Packaging.pdf",
                        D.FINANCIAL_STATEMENT,
                        fin_lines("Sabarmati Corrugated Packaging Pvt Ltd", "FY 2025-26",
                                  912000000, 98000000, 214000000))])
    s.move(68, S.LAPSED, reason="exclusivity_window_expired", hhmm="18:30")

    # ---------------------------------------------------------------- AUR-113 ALLIANCE withdrawn
    s = story("AUR-113", "Kutch Marine Salts — co-marketing alliance", C.ALLIANCE, "neha",
              "kavya", "kutch", R.SELLER)
    s.create(25)
    s.staff(25, add=["bhavesh", "kavya"])
    s.walk([(27, S.QUALIFIED), (31, S.MANDATED)])
    s.move(58, S.WITHDRAWN, reason="client_deprioritised_initiative", hhmm="17:20")

    # ---------------------------------------------------------------- AUR-104 EQUITY
    s = story("AUR-104", "Shivneri Cloud Systems — ₹120 Cr Series C", C.EQUITY,
              "bhavesh", "rohan", "shivneri", R.ISSUER,
              [("vindhya", R.INVESTOR), ("lumen_ridge", R.INVESTOR), ("aravalli", R.INVESTOR)])
    s.create(20)
    s.staff(20, add=["asha", "rohan"])
    s.walk([(22, S.QUALIFIED), (26, S.MANDATED), (29, S.PREPARED), (34, S.MARKETED),
            (42, S.MATCHED), (50, S.BID_AUCTION), (61, S.NEGOTIATION), (80, S.DILIGENCE)],
           mandate=("Raise ₹120 Cr growth equity", M.RAISE,
                    [crit("round_size_inr", "between", [1000000000, 1300000000]),
                     crit("pre_money_inr", "gte", 4400000000),
                     crit("board_seats_offered", "lte", 1),
                     crit("investor_sector_experience", "eq", "B2B SaaS", "soft", 0.7),
                     crit("lead_investor_domicile", "in", ["India", "Singapore"],
                          "preference")],
                    "Pune vertical SaaS for mid-size manufacturers; ARR ₹91 Cr, "
                    "growing 48%. Proceeds for a US go-to-market."),
           financials=[("fs", "FY26 Audited Financial Statements - Shivneri Cloud.pdf",
                        D.FINANCIAL_STATEMENT,
                        fin_lines("Shivneri Cloud Systems Pvt Ltd", "FY 2025-26",
                                  982000000, 61000000, 0)),
                       ("cap", "Cap Table (fully diluted) - Shivneri Cloud.pdf", D.CAP_TABLE,
                        ["Founders 46.2%, ESOP pool 9.5%, Series A/B investors 44.3%"])],
           valuation=("Valuation Report (DCF and ARR multiples) - Shivneri Cloud.pdf",
                      ["Pre-money range INR 455-505 Cr at 5.0-5.6x ARR"], False),
           term_sheet=("Series C Term Sheet - Vindhya Capital lead - signed.pdf",
                       ["INR 120 Cr at INR 480 Cr pre-money",
                        "1x non-participating preference, broad-based anti-dilution"]))
    s.flags(43, ["FEMA: FDI reporting (FC-GPR) for the Singapore investor"])
    s.standard_diligence(81, 90)
    s.doc(82, "qoe", "Quality of Earnings Report - Shivneri Cloud.pdf",
          D.FINANCIAL_STATEMENT,
          ["Quality of earnings review, FY 2025-26",
           "Normalised revenue from operations: 94,30,00,000",
           "Adjusted EBITDA: 4,80,00,000",
           "ARR presented INR 91.0 Cr; normalised ARR INR 86.9 Cr"], sensitivity=3)
    s.job(82, "extract", lambda s=s: {"capability": "extract_financials",
                                      "document_id": s.docs["qoe"]}, hhmm="15:30")
    s.resolve(83, "extract", ["verify"],
              "Checked the two figures against the QoE pages myself; net debt is nil (net "
              "cash), which is why the agent could not find it.",
              "Valuation model refreshed", "Figures disagree with the audited accounts",
              hhmm="11:10")
    s.finding(88, "audited financial", F.ADJUSTMENT,
              "QoE: ARR overstated by ₹4.1 Cr - multi-year prepaid contracts recognised "
              "upfront. At the 5.4x ARR multiple this is ₹22.1 Cr of pre-money.",
              221400000, True, by="rohan")
    s.move(92, S.NEGOTIATION, reason="valuation_reset_after_qoe", hhmm="17:45")
    s.brief(123, "reprice", "valuation_reset", T.MATERIALITY_GATE, lambda now, s=s: package(
        "How should Shivneri respond to Vindhya's repricing request after the QoE "
        "finding?",
        [("accept_458", "Accept ₹458 Cr pre-money", "Founders dilute a further "
          "0.9%; the round closes on the current timeline.", False),
         ("ratchet", "Hold ₹480 Cr with an ARR ratchet", "Price holds if FY27 ARR "
          "beats ₹128 Cr; otherwise investors get bonus shares. Adds 2-3 weeks of "
          "drafting.", True),
         ("walk", "Pause the round", "Re-run the process in Q1 with Aravalli as lead; "
          "about 4 months lost.", True)],
        "ratchet", 0.66,
        "The ARR gap is a recognition-timing issue, not lost revenue; a ratchet prices "
        "that in without conceding the headline.",
        ["QoE found ARR overstated by ₹4.1 Cr (prepaid multi-year contracts).",
         "Deal moved back from DILIGENCE to NEGOTIATION to reset the price.",
         "Vindhya asked for ₹458 Cr pre-money on Friday."],
        [s.ev("qoe", "normalised ARR ₹86.9 Cr"),
         s.ev("term_sheet", "signed at ₹480 Cr pre-money"),
         s.ev("valuation", "range ₹455-505 Cr")],
        "Vindhya's exclusivity lapses and Lumen Ridge may re-open terms.", later(20),
        dissent="Rohan: Lumen Ridge signalled it would follow at ₹458 Cr but not with a "
                "ratchet; the ratchet risks losing the co-investor."),
        221400000, by="rohan", hhmm="16:20")

    # ---------------------------------------------------------------- AUR-103 DEBT CP
    s = story("AUR-103", "Tungabhadra Fincorp — ₹15 Cr term loan", C.DEBT, "bhavesh",
              "asha", "tungabhadra", R.ISSUER,
              [("ujjayini", R.LENDER), ("vindhya", R.LENDER)], counsel="desai_mehta")
    s.create(30)
    s.staff(30, add=["asha", "rohan"])
    s.flags(31, ["RBI: NBFC borrowing - end-use and ALM norms"])
    s.walk([(32, S.QUALIFIED), (35, S.MANDATED), (37, S.PREPARED), (41, S.MARKETED),
            (47, S.MATCHED), (52, S.BID_AUCTION), (58, S.NEGOTIATION), (70, S.DILIGENCE),
            (86, S.DOCUMENTATION), (100, S.CONDITIONS_PRECEDENT)],
           mandate=("Raise ₹15 Cr on-lending term loan", M.RAISE,
                    [crit("facility_amount_inr", "eq", 150000000),
                     crit("tenor_months", "between", [24, 36]),
                     crit("receivables_cover", "gte", 1.1),
                     crit("pricing_pct", "lte", 12.5, "soft", 0.8)],
                    "Karnataka microfinance NBFC (AUM ₹310 Cr) funding its "
                    "Q3 disbursement plan."),
           financials=[("fs", "FY26 Audited Financial Statements - Tungabhadra Fincorp.pdf",
                        D.FINANCIAL_STATEMENT,
                        fin_lines("Tungabhadra Fincorp Pvt Ltd", "FY 2025-26", 612000000,
                                  248000000, 2240000000))],
           valuation=("Portfolio Quality and ALM Review - Tungabhadra Fincorp.pdf",
                      ["GNPA 2.4%, PAR90 2.9%, CRAR 21.6%",
                       "Positive ALM gaps in all buckets up to 1 year"], False),
           term_sheet=("Term Sheet - Ujjayini SFB - accepted.pdf",
                       ["INR 15 Cr, 30 months, 11.9% fixed",
                        "Hypothecation of standard receivables at 1.10x"]),
           definitive=("Term Loan Agreement and Deed of Hypothecation of Receivables - "
                       "Tungabhadra Fincorp - executed.pdf", D.CHARGE_DOCUMENT,
                       ["Loan agreement and deed of hypothecation", "Executed"]),
           overrides={S.CONDITIONS_PRECEDENT: lambda s=s: (
               f"Debt deal: the definitive documents are the loan agreement and deed of "
               f"hypothecation (document #{s.docs['definitive']}, executed). T10 only "
               f"recognises an SPA or SHPA.")})
    s.standard_diligence(71, 82)
    s.signoff(84, "Reviewed against the RBI scale-based regulation for NBFC-ML: end-use "
              "undertaking, ALM statement and CRAR certificate on file. No objection.",
              by="meera")
    s.cp(100, "hyp", "Hypothecation of standard receivables at 1.10x cover; CHG-1 filed",
         "regulatory", hhmm="15:00")
    s.cp(100, "rating", "Fresh external credit rating of BBB+ or better", "commercial",
         hhmm="15:05")
    s.cp(100, "board", "Board resolution under section 180(1)(c)", "corporate", hhmm="15:10")
    s.cp(100, "crar", "Statutory auditor's certificate of CRAR of at least 15%",
         "regulatory", hhmm="15:15")
    s.cp_set(101, "board", "satisfied")
    s.cp_set(102, "rating", "in_progress")
    s.cp_set(104, "hyp", "satisfied")
    s.cp_set(106, "crar", "satisfied")
    s.doc(119, "rating_letter", "Rating Agency Letter - review in progress - Tungabhadra "
          "Fincorp.pdf", D.BOARD_RESOLUTION,
          ["Rating committee scheduled for next month",
           "Indicative outlook: stable"], hhmm="12:20")
    s.brief(121, "rating_cp", "cp_waiver", T.POLICY_REQUIRED, lambda now, s=s: package(
        "Should the lender be asked to waive the BBB+ rating CP and disburse against an "
        "undertaking?",
        [("waive", "Seek a waiver against an undertaking", "Disbursement in 3 days; the "
          "loan reprices +50 bps if the rating comes in below BBB+.", True),
         ("wait", "Wait for the rating", "Disbursement slips about 5 weeks and Q3 "
          "on-lending is delayed.", True),
         ("downsize", "Disburse ₹8 Cr now, ₹7 Cr after the rating",
          "Needs an amendment to the loan agreement.", False)],
        "waive", 0.84,
        "Every other CP is satisfied and the existing rating (BBB, positive) is within one "
        "notch.",
        ["Three of four conditions precedent are satisfied.",
         "The rating committee meets next month."],
        [s.ev("rating_letter", "committee date not fixed"),
         s.ev("definitive", "rating CP in clause 4.1(f)")],
        "The deal stays at CONDITIONS PRECEDENT and the Q3 disbursement plan slips.",
        s.when(122, "10:00"), escalates_to_role="compliance"), 150000000, hhmm="10:00")

    # ---------------------------------------------------------------- AUR-102 DEBT diligence
    s = story("AUR-102", "Panchal Ceramica (Morbi) — ₹85 Cr senior secured term loan",
              C.DEBT, "bhavesh", "kavya", "panchal", R.ISSUER,
              [("narmada", R.LENDER), ("vindhya", R.LENDER)], counsel="sindhu_law")
    s.create(40)
    s.staff(40, add=["asha", "kavya"])
    s.walk([(42, S.QUALIFIED), (46, S.MANDATED), (49, S.PREPARED), (53, S.MARKETED),
            (60, S.MATCHED), (66, S.BID_AUCTION), (75, S.NEGOTIATION), (96, S.DILIGENCE)],
           mandate=("Raise ₹85 Cr senior secured term loan for a new kiln line",
                    M.RAISE,
                    [crit("facility_amount_inr", "between", [800000000, 900000000]),
                     crit("tenor_months", "gte", 72),
                     crit("moratorium_months", "gte", 12),
                     crit("security", "contains", "first charge on fixed assets"),
                     crit("pricing_pct", "lte", 11.0, "soft", 0.7),
                     crit("lender_type", "in", ["credit fund", "NBFC"], "preference")],
                    "Morbi vitrified tile maker adding a 9 MSM/yr GVT kiln; gas-based, "
                    "export orders from the Gulf."),
           financials=[("fs", "FY26 Audited Financial Statements - Panchal Ceramica.pdf",
                        D.FINANCIAL_STATEMENT,
                        fin_lines("Panchal Ceramica Pvt Ltd", "FY 2025-26", 4260000000,
                                  598000000, 1384000000))],
           valuation=("Techno-Economic Viability Study and Asset Valuation - Panchal "
                      "Ceramica.pdf", ["Project cost INR 124 Cr, DSCR 1.48x",
                                       "Fixed asset cover 1.62x"], False),
           term_sheet=("Term Sheet - Narmada Credit Fund - signed.pdf",
                       ["INR 85 Cr, 84 months incl. 12-month moratorium, 10.75%",
                        "First charge on fixed assets, personal guarantees of promoters"]))
    s.standard_diligence(97, 106, skip=("litigation",))
    s.job(98, "extract", lambda s=s: {"capability": "extract_financials",
                                      "document_id": s.docs["fs"]}, hhmm="15:40")
    s.doc(97, "litigation", "Litigation and Regulatory Proceedings Schedule - Panchal "
          "Ceramica.pdf", D.LITIGATION_SUMMARY,
          ["One GST show-cause notice; no other proceedings"], hhmm="11:45")
    s.dd(97, "litigation", "requested", hhmm="10:12")
    s.doc(99, "gst_scn", "GST Show-Cause Notice DRC-01 FY2022-23 - Panchal Ceramica.pdf",
          D.LITIGATION_SUMMARY,
          ["Show-cause notice under section 73, FY 2022-23",
           "Alleged ineligible input tax credit: INR 3.4 Cr plus interest and penalty"],
          hhmm="12:30")
    s.dd(99, "litigation", "received", ["litigation", "gst_scn"], hhmm="16:00")
    s.dd(100, "litigation", "under_review")
    s.finding(101, "litigation", F.RED_FLAG,
              "GST show-cause notice (DRC-01) for FY 2022-23: ₹3.4 Cr of input tax "
              "credit disallowed plus interest and penalty, total exposure ₹5.1 Cr. "
              "Reply filed; no stay.", 51000000, True)
    s.view(101, "gst_scn", "priya", hhmm="17:10")
    s.job(110, "classify_scn", lambda s=s: {"capability": "classify_document",
                                            "document_id": s.docs["gst_scn"]}, live=True)
    s.resolve(110, "classify_scn", ["confirm", "keep"],
              "Reviewed the agent's proposal against the notice itself; recorded the class "
              "a human confirmed.", "Litigation folder complete", "Notice re-issued",
              hhmm="18:20")
    s.move(118, S.DOCUMENTATION, expect_block=True, hhmm="12:00")
    s.brief(124, "gst_exposure", "blocker_resolution", T.MATERIALITY_GATE,
            lambda now, s=s: package(
        "How should the ₹5.1 Cr GST exposure be handled so the facility can move to "
        "documentation?",
        [("escrow", "Escrow ₹5.1 Cr from the first drawdown", "Blocker closes now; "
          "borrower's usable proceeds drop until the GST appeal is decided.", True),
         ("stay", "Wait for an appellate stay order", "Typically 6-10 weeks; the kiln "
          "order slot with the Italian OEM may be lost.", True),
         ("reduce", "Cut the facility to ₹80 Cr", "Lenders' exposure falls; "
          "promoters must bring ₹5 Cr more equity.", False)],
        "escrow", 0.72,
        "Escrow ring-fences the exposure without delaying the kiln order; Narmada has "
        "accepted the same structure before.",
        ["Diligence found a GST show-cause notice with ₹5.1 Cr total exposure.",
         "The litigation blocker is still under review, so T9 blocks DOCUMENTATION.",
         "The move to DOCUMENTATION was attempted and blocked."],
        [s.ev("gst_scn", "DRC-01 notice"), s.ev("litigation", "proceedings schedule"),
         s.ev("term_sheet", "clause 7: material litigation")],
        "The deal stays in DILIGENCE with an open blocker; the kiln order deposit falls "
        "due next week.", later(6),
        dissent="Kavya: the promoters say the notice is a classification dispute that the "
                "tribunal has decided in their favour for other Morbi units - a stay is "
                "likely and escrow ties up cash."),
        51000000, by="kavya", hhmm="10:30")

    # ---------------------------------------------------------------- AUR-108 HYBRID
    s = story("AUR-108", "Deccan Agro Foods — ₹30 Cr CCD round", C.HYBRID, "bhavesh",
              "asha", "deccan", R.ISSUER,
              [("sahyadri", R.INVESTOR), ("vindhya", R.INVESTOR)])
    s.create(55)
    s.staff(55, add=["asha", "kavya"])
    s.walk([(57, S.QUALIFIED), (60, S.MANDATED), (63, S.PREPARED), (68, S.MARKETED),
            (74, S.MATCHED), (80, S.BID_AUCTION)],
           mandate=("Raise ₹30 Cr compulsorily convertible debentures", M.RAISE,
                    [crit("instrument", "eq", "CCD"),
                     crit("amount_inr", "eq", 300000000),
                     crit("conversion_months", "lte", 18),
                     crit("coupon_pct", "lte", 9, "soft", 0.6),
                     crit("investor_type", "in", ["impact fund", "growth fund"],
                          "preference")],
                    "Telangana millet and pulses processor; funds a 40,000 TPA cleaning "
                    "and sorting plant."),
           financials=[("fs", "FY26 Audited Financial Statements - Deccan Agro Foods.pdf",
                        D.FINANCIAL_STATEMENT,
                        fin_lines("Deccan Agro Foods Ltd", "FY 2025-26", 1870000000,
                                  164000000, 422000000))])
    s.move(86, S.MARKETED, reason="lead_bidder_withdrew", hhmm="18:05")
    s.party(94, "aravalli", R.INVESTOR, hhmm="11:15")
    s.move(95, S.MATCHED, hhmm="16:30")
    s.move(103, S.BID_AUCTION, hhmm="16:30")
    s.job(104, "email", lambda s=s: {"capability": "draft_email",
                                     "party_id": s.party_ids["aravalli"],
                                     "brief": "Invite a final CCD term sheet by the 20th "
                                              "with conversion price and coupon."},
          live=True)
    s.resolve(104, "email", ["approve"],
              "Draft states the process deadline and asks for exactly the two terms we "
              "compare on. Approved; I will send it with the bid letter.",
              "Aravalli submits a term sheet", "No term sheet by the deadline", hhmm="18:40")
    s.brief(124, "bidder", "preferred_bidder", T.EXPLICIT_REQUEST, lambda now, s=s: package(
        "Which investor should Deccan Agro grant exclusivity for the ₹30 Cr CCD?",
        [("sahyadri", "Sahyadri Impact Fund", "8.5% coupon, conversion at ₹214/share "
          "in 18 months; asks for a board observer.", True),
         ("aravalli", "Aravalli Growth Fund", "9.0% coupon, conversion at ₹232/share; "
          "wants a 1.5x liquidation preference on conversion.", True),
         ("run_on", "Keep both in play another two weeks", "Better terms possible; both "
          "funds have signalled fatigue.", True)],
        "aravalli", 0.78,
        "Higher conversion price outweighs the 50 bps coupon difference over 18 months.",
        ["Vindhya withdrew as lead; the deal went back to MARKETED, then re-matched.",
         "Two final term sheets are in."],
        [s.ev("fs", "FY26 EBITDA ₹16.4 Cr"), s.ev("nda", "NDA executed")],
        "Both term sheets expire on Friday and the plant order slips a quarter.",
        later(36),
        dissent="Asha: the 1.5x preference makes Aravalli's paper more expensive for the "
                "promoters in a down case."),
        300000000, hhmm="09:50")

    # ---------------------------------------------------------------- AUR-105 EQUITY secondary
    s = story("AUR-105", "Malabar Spice & Condiments — pre-IPO secondary", C.EQUITY, "neha",
              "kavya", "coromandel", R.SELLER, [("nilgiri", R.BUYER)])
    s.create(70)
    s.staff(70, add=["bhavesh", "kavya"])
    s.party(72, "malabar", R.TARGET, hhmm="10:35")
    s.walk([(72, S.QUALIFIED), (76, S.MANDATED), (80, S.PREPARED), (88, S.MARKETED)],
           mandate=("Sell a 6.8% pre-IPO stake (₹65 Cr)", M.SELL,
                    [crit("stake_pct", "eq", 6.8),
                     crit("price_per_share_inr", "gte", 575),
                     crit("lock_in_acceptance", "eq", "6 months post listing"),
                     crit("buyer_type", "in", ["family office", "AIF"], "soft", 0.5)],
                    "Coromandel's fund life ends next year; it wants out before the DRHP."),
           financials=[("fs", "FY26 Audited Financial Statements - Malabar Spice.pdf",
                        D.FINANCIAL_STATEMENT,
                        fin_lines("Malabar Spice & Condiments Ltd", "FY 2025-26",
                                  5240000000, 702000000, 380000000)),
                       ("cap", "Shareholding Pattern - Malabar Spice.pdf", D.CAP_TABLE,
                        ["Promoters 71.4%, Coromandel 6.8%, others 21.8%"])])
    s.brief(90, "floor", "pricing", T.EXPLICIT_REQUEST, lambda now, s=s: package(
        "What floor price should Coromandel set for the pre-IPO block?",
        [("floor_612", "Floor ₹612 per share", "About 18x FY26 earnings; may thin "
          "the buyer list.", True),
         ("floor_575", "Floor ₹575 per share", "Mandate minimum; faster close.", True),
         ("no_floor", "No floor, run price discovery", "Signals a forced seller.", True)],
        "floor_612", 0.81,
        "Listed peers trade at 22-24x; a pre-IPO discount of 20-25% gives ₹600-640.",
        ["Two family offices have asked for the information memorandum."],
        [s.ev("fs", "FY26 PAT basis"), s.ev("cap", "6.8% block")],
        "The teaser goes out without a floor.", now + timedelta(hours=24)),
        650000000, hhmm="11:30")
    s.resolve(91, "floor", ["floor_612"],
              "Peers support it and Coromandel is not a forced seller until next year. Start "
              "at 612 and review after the first round of feedback.",
              "First round of buyer feedback", "Fewer than two buyers above ₹575",
              by="neha", hhmm="10:15")

    # ---------------------------------------------------------------- AUR-114 DEBT rejected
    s = story("AUR-114", "Chambal Agro Warehousing — ₹22 Cr warehouse receipt line",
              C.DEBT, "vikram", "rohan", "chambal", R.ISSUER)
    s.create(45)
    s.staff(45, add=["rohan"])
    s.walk([(47, S.QUALIFIED)])
    s.doc(50, "kyc", "KYC and Adverse Media Report - Chambal Agro Warehousing.pdf",
          D.LITIGATION_SUMMARY, ["Promoter named in two pending cheque-bounce cases",
                                 "Related-party warehouse leased to a defaulting trader"])
    s.move(52, S.REJECTED, reason="kyc_adverse_promoter_findings", hhmm="17:30")

    # ---------------------------------------------------------------- AUR-109 JV
    s = story("AUR-109", "Satpura Motion Controls x Rheintal — servo drives JV", C.JV,
              "bhavesh", "rohan", "satpura", R.SELLER, [("rheintal", R.INVESTOR)],
              counsel="desai_mehta")
    s.create(78)
    s.staff(78, add=["asha", "rohan"])
    s.walk([(80, S.QUALIFIED), (84, S.MANDATED), (87, S.PREPARED), (93, S.MARKETED),
            (108, S.MATCHED)],
           mandate=("Form a 51:49 servo-drive manufacturing JV with technology transfer",
                    M.PARTNER,
                    [crit("indian_holding_pct", "gte", 51),
                     crit("technology_licence", "contains", "servo drive firmware"),
                     crit("royalty_pct", "lte", 4.0, "soft", 0.8),
                     crit("partner_country", "not_in", ["land-border countries"]),
                     crit("plant_location", "eq", "Pithampur", "preference")],
                    "Satpura brings the plant and customers; Rheintal brings the drive "
                    "platform and 49% equity."),
           financials=[("fs", "FY26 Audited Financial Statements - Satpura Motion "
                        "Controls.pdf", D.FINANCIAL_STATEMENT,
                        fin_lines("Satpura Motion Controls Pvt Ltd", "FY 2025-26",
                                  1340000000, 157000000, 268000000))])
    s.flags(94, ["FEMA: FDI under the automatic route", "Press Note 3: beneficial-owner "
                 "check"], by="priya")
    s.brief(125, "royalty", "commercial_terms", T.EXPLICIT_REQUEST, lambda now, s=s: package(
        "Should Satpura accept Rheintal's 5% technology royalty or counter at 3.5%?",
        [("accept", "Accept 5%", "JV margin falls about 1.6 points; signing in 3 weeks.",
          True),
         ("counter", "Counter at 3.5% stepping to 4%", "Within the mandate; Rheintal may "
          "ask for a larger equity share.", True)],
        "counter", 0.81,
        "The mandate caps royalty at 4%; FEMA permits either under the automatic route.",
        ["Rheintal's draft JV term sheet arrived with a 5% royalty on net sales."],
        [s.ev("nda", "NDA executed"), s.ev("fs", "Satpura FY26 margins")],
        "The JV term sheet stays unsigned and Rheintal's board meeting passes.", later(47)),
        None, by="rohan", hhmm="11:20")

    # ---------------------------------------------------------------- AUR-110 LPGP
    s = story("AUR-110", "Nilgiri Family Office — ₹25 Cr LP commitment", C.LPGP, "neha",
              "kavya", "nilgiri", R.INVESTOR)
    s.create(100)
    s.staff(100, add=["bhavesh", "asha", "kavya"], remove=["meera"])
    s.party(103, "aravalli", R.ISSUER, hhmm="10:50")
    s.walk([(103, S.QUALIFIED), (108, S.MANDATED), (114, S.PREPARED)],
           mandate=("Commit ₹25 Cr to a Category II AIF", M.DEPLOY,
                    [crit("fund_category", "eq", "SEBI Category II AIF"),
                     crit("commitment_inr", "between", [200000000, 250000000]),
                     crit("manager_prior_funds", "gte", 2, "soft", 0.5),
                     crit("sector_focus", "in", ["healthcare", "consumer"], "preference")],
                    "Family office diversifying out of listed equity; Aravalli Fund III is "
                    "the first candidate."))

    # ---------------------------------------------------------------- AUR-115 MNA mandated
    s = story("AUR-115", "Chilika Aqua Exports — buy-side acquisition of a shrimp processor",
              C.MNA, "neha", "asha", "chilika", R.BUYER)
    s.create(105)
    s.staff(105, add=["bhavesh", "asha"])
    s.walk([(108, S.QUALIFIED), (116, S.MANDATED)])

    # ---------------------------------------------------------------- AUR-116 DEBT qualified
    s = story("AUR-116", "Bundelkhand Solar Parks — ₹180 Cr project finance", C.DEBT,
              "vikram", "kavya", "bundelkhand", R.ISSUER)
    s.create(115)
    s.staff(115, add=["bhavesh", "asha", "kavya"])
    s.walk([(119, S.QUALIFIED)])

    # ---------------------------------------------------------------- AUR-117 originated
    s = story("AUR-117", "Konkan Coastal Logistics — cold-chain alliance", C.ALLIANCE,
              "bhavesh", "asha", "konkan", R.SELLER)
    s.create(122)
    s.staff(122, add=["asha"])
    return stories


def _use_database(name: str) -> None:
    """Point AURA_DATABASE_URL / AURA_MIGRATION_DATABASE_URL at database `name` on the same
    server, creating it (as the schema owner) when it does not exist yet."""
    from sqlalchemy import create_engine, make_url, text

    from aura.config import get_settings
    s = get_settings()
    if not s.migration_database_url:
        raise SystemExit("--db needs AURA_MIGRATION_DATABASE_URL (the aura_owner connection)")
    owner = make_url(s.migration_database_url)
    admin = create_engine(owner.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        if not conn.scalar(text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": name}):
            conn.execute(text(f'CREATE DATABASE "{name}"'))
    admin.dispose()
    os.environ["AURA_DATABASE_URL"] = make_url(s.database_url).set(
        database=name).render_as_string(hide_password=False)
    os.environ["AURA_MIGRATION_DATABASE_URL"] = owner.set(
        database=name).render_as_string(hide_password=False)
    get_settings.cache_clear()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m aura.data.demo", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--with-agents", action="store_true",
                    help="run two agent jobs on the live CrewAI + Ollama crew (slow)")
    ap.add_argument("--db", help="PostgreSQL database to build into, on the same server "
                    "(default: the one AURA_DATABASE_URL names). Created if missing.")
    args = ap.parse_args(argv)
    if args.db:
        if "aura.data.engine" in sys.modules:
            ap.error("--db must be given before the database engine is created; run it as "
                     "its own command")
        _use_database(args.db)

    # Imported here so --db takes effect before the engine is created.
    from aura.core.clock import use_clock
    from aura.data.demo_engine import Desk, ReplayClock, at, business_days
    from aura.data.demo_story import add_users, ensure_deal_exists
    from aura.data.engine import SessionLocal
    from aura.data.filestore import LocalFileStore
    from aura.data.seed import seed
    from aura.data.verify_audit import default_anchor_path, refresh_anchor
    from aura.data.walls import SYSTEM
    from aura.core.services.handoffs import escalate_overdue
    from aura.data.demo_engine import NullEvents
    from aura.worker.stub_orchestrator import StubOrchestrator

    seed()
    run_now = datetime.now(timezone.utc)
    days = business_days(HORIZON_DAYS, run_now.astimezone(timezone(timedelta(hours=5,
                                                                              minutes=30)))
                         .date())
    live = None
    if args.with_agents:
        from aura.agents.factory import make_orchestrator
        live = make_orchestrator()
        if isinstance(live, StubOrchestrator):
            print("Ollama is not reachable: --with-agents falls back to the stub.")
            live = None

    clock = ReplayClock(at(days[0], "09:00"))
    with SessionLocal() as session, use_clock(clock):
        desk = Desk(session, clock, LocalFileStore(), StubOrchestrator(), live)
        add_users(desk, days[0])
        stories = build(desk, days, run_now)
        existing = [st for st in stories if ensure_deal_exists(st)]
        todo = [st for st in stories if st not in existing]
        if not todo:
            # Nothing to build; the stories' events were scheduled but are discarded.
            desk.events = [e for e in desk.events if e.label == "team onboarded"]
        else:
            keep = {st.ext for st in todo}
            desk.events = [e for e in desk.events
                           if e.label == "team onboarded" or e.label.split(" ")[0] in keep]

            def sweep():
                r = desk.repos(SYSTEM)
                escalate_overdue(r.handoffs, r.audit, NullEvents())
            desk.schedule(at(days[122], "10:05"), "escalation sweep", sweep)
        for st in existing:
            print(f"  {st.ext} already present - left as it is")
        n = desk.run_all()
        session.commit()
    print(f"Demo data: {len(todo)} deal(s) built, {len(existing)} already present, "
          f"{n} events replayed.")
    for st in todo:
        print(f"  {st.ext:8} {st.cls.value:9} {(st.final_stage.value if st.final_stage else 'ORIGINATED'):<22} "
              f"{st.name}")
    with SessionLocal() as session:
        result = refresh_anchor(session, default_anchor_path())
    print(f"Audit chain: {result.message}")
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
