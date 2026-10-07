# Aura — Market Research & Feature Benchmark

**Date:** 2026-10-07 · **Compares:** Aura v1 (branch `feature/aura-v1-deal-spine`) with real-world deal, data-room, AI and compliance platforms.

> **How reliable this is.** The competitor findings come from web-search result snippets. Vendor pages were not opened. Pricing and India-presence details in particular are indicative, so check them before using them in a decision. Sources are linked inline. Several are third-party review or aggregator pages, so treat them as secondary.

---

## 1. Summary

- **No single real-world product does everything Aura does.** Today an Indian bank or PE firm usually combines three or four tools: a deal CRM (e.g. DealCloud), a data room (Datasite, Intralinks), a walls/conflicts system (Intapp), and SEBI insider-trading compliance software (Volody).
- **Aura has 36 of 65 market-standard features, with 4 more partly built and 25 missing.** That is about 55% of what established platforms offer combined, or about 62% counting the partial features.
- **Aura's strengths are where the incumbents are weakest:** stage moves blocked by rules, AI that hands people decisions, a local on-premise model, Indian regulation built into the workflow, and walls plus a tamper-evident audit trail in one product.
- **The biggest gap is the data room.** Seven features that buyers expect from Datasite or Ansarada are missing.

---

## 2. Comparable platforms

### 2.1 Deal pipeline / CRM

| Platform | What it does | Notes |
|---|---|---|
| [Intapp DealCloud](https://www.intapp.com/investment-banking/) | Deal and relationship CRM for banks and PE | Pricing not public; [Vendr](https://vendr.com/marketplace/dealcloud) reports ~$59K–$375K/yr (median ~$146K). Pairs with Intapp Walls/Conflicts |
| [Midaxo](https://midaxo.com/) | Corporate-development M&A lifecycle platform | 500+ teams; a Leader in IDC MarketScape AI-Enabled Deal Management 2025 |
| [DealRoom](https://dealroom.net/m-a-software-companies-comparison) | Pipeline, diligence and integration in one | — |
| Devensoft | Acquisition and integration management | Enterprise integration focus ([source](https://www.topbestalternatives.com/devensoft/)) |

### 2.2 Virtual data rooms

| Platform | What it does | Notes |
|---|---|---|
| [Ansarada](https://www.ansarada.com/article/best-ai-data-rooms-due-diligence-2026) | AI data room: AI-Sort, AI-Redact, AI-Translate, AI-Predict, the "Ask Aida" assistant, bidder tracking | Covers M&A, capital raising and restructuring |
| Datasite / Intralinks | The dominant data rooms; used by Indian banks and PE ([source](https://cxotoday.com/daily-news/top-virtual-data-rooms-powering-indias-ma-and-ipo-boom-in-2025/)) | Intralinks is strong on cross-border deals, Q&A and fine-grained permissions ([source](https://dealroom.net/compare/dealroom-vs-intralinks)) |
| CDR | Indian data room hosted in MeitY-approved data centres | Shows that data residency is a buying criterion in India |

### 2.3 AI-native diligence

| Platform | What it does |
|---|---|
| Rogo | Sell-side banking AI: comparables, models, pitchbooks, screening of CIMs and data rooms, diligence memos ([source](https://www.hebbia.com/resources/hebbia-vs-rogo); vendor-written comparison) |
| Hebbia | Research and diligence across many documents at scale |
| [Brightwave](https://www.brightwave.io/comparison/brightwave-vs-rogo-ai) | Reads data rooms and produces reports and decks for private-markets diligence |

All the AI vendors found are cloud-based.

### 2.4 Marketplaces / matching

| Platform | What it does |
|---|---|
| Axial | Private deal network for the North American lower mid-market, revenue $5M–$250M ([source](https://us.fitgap.com/products/axial)) |
| [SMERGERS](https://www.businesstoday.in/latest/deals/story/smergers-an-online-matchmaking-platform-for-smes-308935-2021-10-09) | Bengaluru SME M&A marketplace; ~70K screened businesses (2021); revenue from subscriptions, services and success fees |
| [Yubi (formerly CredAvenue)](https://yourstory.com/2022/06/fintech-unicorn-credavenue-rebrands-yubi) | Indian debt marketplace; reported >₹1.5 lakh crore disbursed (2023) |

### 2.5 Indian data and infrastructure

| Platform | Role for Aura |
|---|---|
| [Tracxn](https://www.capterra.in/software/204090/tracxn) | Company and market intelligence (3.1M+ companies). A possible data source |
| [Venture Intelligence](https://blog.ventureintelligence.com/?p=1179) | Indian PE/VC deal and exit database. A possible data source |
| Account Aggregators: Sahamati, Finvu, [OneMoney](https://developer.moneyone.in/) | RBI-regulated, consent-based sharing of financial data. Infrastructure Aura could connect to, not a competitor |

### 2.6 Compliance, walls and UPSI

| Platform | What it does |
|---|---|
| [Intapp Walls / Conflicts / Employee Compliance](https://www.intapp.com/investment-banking/) | Ethical walls, AI-assisted conflict clearance, attestations; enforces walls inside Harvey ([source](https://www.01net.it/intapp-to-partner-with-harvey-bringing-ethical-wall-enforcement-directly-into-the-platform/)) |
| [Volody PIT](https://blog.volody.com/?p=1330) | SEBI insider-trading compliance software: insider-information record (SDD), trading windows, pre-clearance, audit trail |

**Regulatory note.** SEBI requires the Structured Digital Database (SDD) to be tamper-proof, time-stamped, audit-trailed and preserved for 8 years ([source](https://vinodkothari.com/2020/07/sebi-prescribes-norms-for-structured-digital-database-system-driven-disclosures-coc-violations/)). Aura's hash-chained audit already meets the tamper-evidence part. An intermediary that shares UPSI also takes on an SDD entry obligation.

---

## 3. Capability matrix

✓ = has it · partial = some of it · ✗ = doesn't · ? = not verified

| Platform | Pipeline | Data room | Diligence | AI agents | Matching / auction | Walls / compliance | Audit | India-specific | On-prem |
|---|---|---|---|---|---|---|---|---|---|
| DealCloud | ✓ | ✗ | partial | partial | ✗ | partial (Intapp suite) | partial | ✗ | ? |
| Midaxo | ✓ | ✗ | ✓ | partial | ✗ | ✗ | partial | ✗ | ✗ |
| DealRoom | ✓ | partial | ✓ | partial | ✗ | ✗ | partial | ✗ | ✗ |
| Ansarada | partial | ✓ | ✓ | ✓ | partial (bidder tracking) | ✗ | ✓ | ✗ | ✗ |
| Datasite / Intralinks | partial | ✓ | ✓ | partial | partial | ✗ | ✓ | partial | ✗ |
| CDR (India) | ✗ | ✓ | partial | ? | ✗ | ✗ | ? | ✓ | partial (India-hosted) |
| Rogo / Hebbia | ✗ | ✗ | partial | ✓ | ✗ | ✗ | ? | ✗ | ✗ |
| Intapp Walls | ✗ | ✗ | ✗ | partial | ✗ | ✓ | ✓ | ✗ | ? |
| Volody PIT | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ (SDD only) | ✓ | ✓ | ? |
| SMERGERS | ✗ | partial | ✗ | ✗ | ✓ (SME) | ✗ | ✗ | ✓ | ✗ |
| Yubi | partial | ✗ | partial | ? | ✓ (debt) | ✗ | ? | ✓ | ✗ |
| **Aura v1** | **✓ (rule-enforced)** | **✓** | **✓** | **✓ (local)** | ✗ (SOSPE vision) | **✓ (walls also bind AI agents)** | **✓ (hash chain + anchor)** | **partial** (identifier checks built; MCA21 lookup not) | **✓** |

**Closest overall competitors**

1. **Intapp (DealCloud + Walls/Conflicts).** The nearest on pipeline, walls and audit, and a credible bundle for the same buyer. It is cloud-based, not India-specific, and has no AI decision handoff.
2. **Ansarada.** The nearest on data room, diligence, AI and the auction lifecycle. It is cloud-only, with no rule-enforced pipeline and no walls.
3. **Midaxo / DealRoom.** The nearest on pipeline plus diligence checklists. Neither has walls, UPSI handling or an India focus.

---

## 4. Aura feature benchmark (65 market-standard features)

**Totals: 36 have · 4 partial · 25 missing**

| Area | Compared with | Have | Partial | Missing |
|---|---|---|---|---|
| A. Deal pipeline | DealCloud, Midaxo, DealRoom | 8 | 2 | 4 |
| B. Data room | Datasite, Intralinks, Ansarada | 4 | 1 | 7 |
| C. Diligence | Midaxo, DealRoom, Ansarada | 5 | 0 | 1 |
| D. AI | Rogo, Hebbia, Ansarada AI | 6 | 0 | 2 |
| E. Compliance and walls | Intapp Walls, Volody | 7 | 1 | 2 |
| F. Marketplace and outreach | Axial, SMERGERS, Yubi | 0 | 0 | 3 |
| G. India data | Tracxn, Probe42, Account Aggregators | 2 | 0 | 2 |
| H. Platform | all | 4 | 0 | 4 |

### A. Deal pipeline (8 / 2 / 4)
- ✅ Deals list with filters, grouping and density
- ✅ 12 standard stages (SOSPE vocabulary)
- ✅ **Stage moves blocked by rules stored as data**, with recorded evaluations and role-scoped overrides (ahead of the competitors)
- ✅ Stage history and time-in-stage analytics
- ✅ Dashboard with headline numbers and stage funnel
- ✅ Parties with statutory identifiers
- ✅ Mandates with hard/soft/preference criteria
- ✅ ⌘K command palette and search
- 🟡 Tasks: they exist only as AI handoffs; there's no to-do list for people
- 🟡 Notifications: in-app live updates and badges, no email
- ❌ Relationship tracking with email and calendar capture
- ❌ Contacts/people directory
- ❌ Notes and comments on a deal
- ❌ Report export (Excel/PDF)

### B. Data room (4 / 1 / 7)
- ✅ Upload with document types
- ✅ Versioning
- ✅ UPSI sensitivity levels (UPSI forced to level 4)
- ✅ View and download access log
- 🟡 Permissions per deal (the deal team), not per folder or per user
- ❌ Folder structure and document index
- ❌ Watermarking
- ❌ Q&A module
- ❌ AI redaction
- ❌ Bidder engagement analytics
- ❌ In-browser document preview
- ❌ Full-text search across documents

### C. Diligence (5 / 0 / 1)
- ✅ Checklists from templates
- ✅ Blockers with evidence
- ✅ Findings with ₹ impact
- ✅ Conditions precedent
- ✅ Financial extraction with the 0.95-confidence gate before it feeds valuation
- ❌ Request lists sent to outside parties (no client portal)

### D. AI (6 / 0 / 2)
- ✅ Document classification
- ✅ Financial extraction
- ✅ Outreach email drafting (never sent automatically)
- ✅ **Structured decision handoffs:** options, recommendation, confidence, "if you do nothing" (unique to Aura)
- ✅ Record of every model run, with prompt drill-down
- ✅ **Local, on-premise model** (unique to Aura)
- ❌ Chat with your documents
- ❌ Generation of comparables, financial models and pitchbooks

### E. Compliance and walls (7 / 1 / 2)
- ✅ Deal walls (they also apply to AI agents)
- ✅ Four roles: dealmaker, analyst, compliance, admin
- ✅ Regulatory flags with compliance sign-off
- ✅ Rule overrides that need a written justification
- ✅ Hash-chained audit trail with anchor file
- ✅ Audit verification view
- ✅ Success metrics (PRD §11)
- 🟡 SEBI insider-information record (SDD): UPSI flags and the audit trail exist, but there's no insider list or export
- ❌ Conflict check when a deal is opened
- ❌ Employee attestations

### F. Marketplace and outreach (0 / 0 / 3), all SOSPE vision and out of scope for v1
- ❌ Counterparty matching
- ❌ Auctions with bid normalisation
- ❌ Actually sending messages (drafts only, by design)

### G. India data (2 / 0 / 2)
- ✅ CIN/PAN/GSTIN/DIN/LLPIN format checks (in the app and the database)
- ✅ ₹ lakh/crore formatting
- ❌ Live MCA21 company lookup
- ❌ Account Aggregator integration

### H. Platform (4 / 0 / 4)
- ✅ Admin user management
- ✅ Light and dark themes, keyboard-first, WCAG AA
- ✅ REST API with OpenAPI docs
- ✅ Live real-time updates (WebSocket, filtered by deal wall)
- ❌ SSO and multi-factor login
- ❌ External client and bidder portals
- ❌ Mobile app
- ❌ Cloud or multi-firm hosting (left out by design: local-only)

---

## 5. Positioning

**Where Aura is genuinely different**

1. **Integration.** Pipeline, data room, diligence, walls, audit and AI agents in one product. Buyers otherwise stitch three or four tools together.
2. **On-premise with a local model.** Every AI competitor found is cloud-based. Data residency already matters to Indian buyers (see CDR).
3. **Stage moves blocked by rules**, tied to diligence blockers, UPSI and compliance sign-off.
4. **AI hands people decisions, not drafts.** This is a new framing but easy to copy, so speed matters.
5. **Indian regulation in the workflow.** RBI, FEMA and CCI flags gate stage moves, and the audit design matches SEBI's SDD requirements.

**Where incumbents are stronger**

- Data room depth (Datasite, Intralinks, Ansarada): AI redaction, translation, bidder analytics, certifications, 24/7 support.
- Relationship intelligence and email/calendar capture (DealCloud).
- Indian company and deal data (Tracxn, Venture Intelligence).
- A network of buyers and sellers (Axial, SMERGERS). Matching is weak without one.
- Maturity of enterprise walls and conflicts (Intapp).

---

## 6. Recommended next features (PRD-v2 candidates)

| # | Feature | Closes gap in | Why first |
|---|---|---|---|
| 1 | Document preview + full-text search | B. Data room | The first thing a data-room user notices is missing |
| 2 | Data-room folder index + Q&A module | B. Data room | Expected by every bidder and counsel |
| 3 | Conflict check at deal intake | E. Compliance | Standard in Intapp; fits Aura's party data and walls |
| 4 | SEBI SDD export (8-year retention, sharer/recipient, per UPSI entry) | E. Compliance | Turns the hash-chained audit into a regulatory deliverable |
| 5 | Live MCA21 company lookup | G. India data | Verified identifiers and financials for smaller targets |

Other ideas from the research:
- Ansarada-style AI redaction and bidder analytics, which also support the sealed-bid auction vision.
- DealCloud-style relationship and email capture, to feed deal origination.
- Account Aggregator consent flows (Finvu, OneMoney), for verified financials where audited data is thin.

---

## 7. Follow-up research gaps

- Pricing for most vendors (only DealCloud is reported).
- Whether Intapp and DealCloud can run on-premise.
- India presence of the deal CRMs (Midaxo, DealRoom, Affinity).
- Not yet researched: Affinity, 4Degrees, Navatar, Altvia, SourceScrub, Grata, Firmex, iDeals, Kira/Litera, Luminance, Harvey, Dealsuite, StarCompliance, ComplySci, Probe42, Tofler, and human-in-the-loop AI workflow platforms for finance.
