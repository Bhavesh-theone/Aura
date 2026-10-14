# Aura — Expert Review and Improvement Roadmap

**Date:** 2026-10-14 · **Branch reviewed:** `feature/postgres-pgvector` (head `0f0e9bf`) · **Method:** three independent, read-only expert reviews, combined into this report:
1. Indian investment banking and compliance (SEBI PIT, FEMA, CCI, RBI, Companies Act, DPDP, IBC).
2. Principal engineering and security.
3. Product and AI quality, with a walk through the live UI as all four roles.

The most serious claims were re-checked directly in the code (marked ✔ verified).

> **Regulatory caveat:** the following were flagged by the domain reviewer as needing confirmation by a practising lawyer before you rely on them: current CCI thresholds, DPDP Rules 2025 commencement dates, SDD obligations that apply to intermediaries, the RBI LEI exposure threshold, and the status of Rule 11UA after 2024.

---

## 1. Verdict

| Lens | Verdict |
|---|---|
| Domain and compliance | **Internal pilot on historical or anonymised deals only.** Not ready for live mandates that carry UPSI. |
| Engineering | **Well-built single-user prototype. Not production-ready.** About 3–5 engineer-weeks to clear the top items. |
| Product and AI | **A compliance-grade deal spine, not yet a daily workspace.** The AI is safe because it is heavily gated, not because it is accurate. |

**What is genuinely strong:**
- deterministic, data-driven stage rules;
- decision handoffs that state "if you do nothing";
- every model run recorded;
- deal walls enforced by Postgres row-level security, which also binds the AI agents;
- a hash-chained audit trail;
- local-only AI;
- intake with citations;
- a disciplined layered codebase with 817 tests.

**No competitor reviewed combines all of these** (see `docs/market-research.md`).

**Readiness ladder:**
1. **Wave 0 + Wave 1** (below) → **controlled pilot with real, non-UPSI deals.**
2. **Wave 2** → **controlled pilot with live UPSI mandates.**
3. **Wave 3** → **production.**

---

## 2. Critical findings (fix before any real use)

| # | Finding | Lens | Evidence | Fix |
|---|---|---|---|---|
| C1 | **The JWT signing secret is the public default.** Anyone can forge a token for any user, including admin. | Eng | ✔ verified: `backend/.env` holds `dev-secret-change-me`, which is also the default in `config.py` | Refuse to start on a default or short secret; rotate it; move to PyJWT with `aud`/`iss`/`jti` |
| C2 | **A dealmaker can bypass compliance sign-off.** The T9 rule passes when regulatory flags are empty, and dealmakers can edit those flags. A sign-off is not bound to the flags it reviewed. | Domain | ✔ verified: `rbac_policy.py:47`, `seed.py:76` | Only compliance may remove flags. Bind each sign-off to a hash of the flags and profile; invalidate it when they change |
| C3 | **There is no SEBI PIT Structured Digital Database** (who received UPSI, for what purpose, when, and until when; 8-year tamper-proof retention). Intake documents are hard-coded as non-UPSI. | Domain + Product | `documents.py:42`, `intake.py:198`; `market-research.md:172` | A first-class UPSI register with external recipients (PAN), purpose, notice and cleansing date; a WORM-anchored 8-year hold; UPSI on by default for listed targets |
| C4 | **Compliance cannot see the whole book.** Walls hide deals from compliance too, so there are no restricted or watch lists, no conflict check across deals, and no wall-crossing approval. | Domain | `walls.py:1-17`, `services/walls.py:15` | A compliance "control-room" read scope; restricted lists keyed on CIN/ISIN; a wall-crossing workflow; conflict check at intake |
| C5 | **One set of stage rules for every deal type, and self-override.** "2 counterparties", "valuation report" and "SPA only" are wrong for bilateral debt, JVs, LP/GP and alliances. A dealmaker can override most rules alone. | Domain | `seed.py:41-92`, `transition_deal.py:72-80` | Rule sets per deal type, and maker-checker overrides that need a second, senior approver |
| C6 | **No deployment, CI, backups or disaster recovery.** No app Dockerfile, no pipeline, no Postgres or file-store backups. | Eng | repository | Containerise; CI gates; WAL/point-in-time recovery; object store; a tested restore runbook |

---

## 3. High-priority findings by area

### Security (engineering)
- **Demo users with weak passwords are seeded on every start** (`seed.py:28`, `main.py:62`). Login has no throttling or lockout, unknown users can be enumerated by timing, and the minimum password length is 1.
- **Login tokens can't be revoked or refreshed** (8-hour lifetime). A deactivated user's WebSocket keeps receiving firm-wide events.
- **Tokens are stored in `localStorage` and passed in the WebSocket query string.** There's no CSP or security headers. `python-jose` has open CVEs (CVE-2024-33663/33664).
- **The row-level security trust boundary is the app role itself.**
  - The app role can rewrite `stage_guard.sql_text`, and that SQL is executed verbatim (`sql_deals.py:157`): a stored-SQL risk.
  - The audit insert policy is `WITH CHECK (true)`.
  - The audit chain is unkeyed, and its anchor is on the same host.
- **Uploads are thinly checked:** the file extension is trusted over the magic bytes, there are no zip-bomb limits and no AV scan, and parsing runs inside the API process.
- **Postgres is published on all interfaces** (✔ verified: `compose.yaml` `5433:5432`, and RUNNING.md wrongly says localhost), using dev passwords.

### Architecture, operations, performance (engineering)
- **Workers run as daemon threads inside the API process.** With N API processes you get N copies, and the limits that should be global aren't:
  - the LLM concurrency cap and rate limiters only work within one process;
  - the WebSocket hub doesn't span processes.
- **The audit advisory lock serialises every audited transaction across the app.**
- **The whole audit chain is re-verified** on login, on metrics, on every export, every 60 s and at startup. That's O(N), and any user can trigger it, so it's a DoS vector.
- **Operations gaps:**
  - observability: the health check is static, there's no readiness check, metrics or JSON logs, and traces stay local only;
  - no graceful shutdown;
  - no statement timeouts;
  - the dashboard loads every deal into Python.
- **Code hygiene:**
  - a bad merge left duplicate dependency functions (✔ verified: `deps.py:219`/`239`);
  - `@app.on_event` is deprecated;
  - there's no ruff, mypy, coverage or frontend test runner.

### Indian deal practice and compliance (domain)
- **Missing regulatory gates:**
  - client KYC and beneficial owners, PEP/sanctions screening;
  - an NDA with **the specific counterparty** before data is shared (T5 accepts any NDA on the deal);
  - board and special resolutions (Companies Act s.180/186/188/42/62);
  - a registered valuer (s.247), FEMA pricing, Rule 11UA;
  - CCI tests, including the deal-value threshold;
  - SEBI SAST open-offer triggers and ICDR pricing for listed targets;
  - FEMA FC-GPR/FC-TRS, Press Note 3, ODI, ECB;
  - CHG-1/CERSAI and stamp duty;
  - IBC/NCLT timelines.

  The JSON profile fields for these (`cci_route`, `open_offer_triggered`, `press_note_3` and others) exist but nothing reads them.
- **No post-closing filings stage** with due dates.
- **Diligence checklists are a placeholder:** 8 templates, against the 150–400 items of real Indian diligence. Analysts can waive blockers with any free text, and there's no materiality threshold relative to deal size. A closed deal still had open material items.
- **The data model is thin:**
  - no beneficial owners, directors, country or listed status on parties;
  - missing identifiers: LEI, UDYAM, TAN, ISIN, CKYC; no checksum validation;
  - **no mandate economics:** retainer, success-fee slabs, tail, exclusivity, GST;
  - debt, equity and M&A profiles lack DSCR, a real cap table, the EV-to-equity bridge, earn-outs, escrow and indemnities.
- **DPDP controls are deferred:** purpose and retention per record, erasure reconciled with legal hold, a breach log.
- **Outbound has no check on an executed NDA or the UPSI register before sending,** and the email body isn't stored.

### Product and UX (product)
- **No human collaboration:** no notes, comments, @mentions, or owners and due dates on diligence items and conditions. Teams will coordinate in WhatsApp instead.
- **No notifications:** no email, digest or reminders. 7 of 9 open decisions had escalated "to the same dealmaker" without anyone being told.
- **No partner economics:** no pipeline ₹ value, fee forecast, close probability or stage targets.
- **Mobile is broken at 390px,** and partners approve decisions on their phones.
- **No search across deals, parties and documents. No in-browser document preview.**
- **Internal jargon and raw errors show in the UI,** such as `ValueError…`, `blocker_resolution`, and CLI commands on the Integrations page.

### AI quality (product)
- **The evaluation sets are small and synthetic,** so the 1.00 scores likely overfit. Validate on about 50 real, redacted Indian deal packs.
- **`extract_financials` is weak (0.42).** Its prompt reads only the first-text excerpt. Route it through Docling table grids plus deterministic parsing, as intake already does.
- **Confidence is the model's own self-report.** Calibrate per capability (reliability curve, ECE) and derive confidence from grounding, agreement between sources and OCR quality.
- **Too many decisions are raised.** 14 of 21 resolved handoffs were `policy_required`, and classifications had 0 overrides yet always go to a person. Batch-confirm, auto-confirm when the override rate is low, and suppress garbage-in cases.
- **No reranker,** and the full-text fallback turns AND into OR. Add a local cross-encoder over the top 30 results.
- **A single 4B CPU model with no upgrade path.** `pinned_model` is unused, and intake takes about 5 minutes for 6 files.

---

## 4. Roadmap

Effort: S ≤ 1 week, M 1–3 weeks, L > 3 weeks.

### Wave 0 — Stop-ship fixes (about 1 week)
| # | Item | Effort |
|---|---|---|
| 0.1 | Fail startup on a default or weak JWT secret; rotate it; PyJWT with `aud`/`iss`/`jti` (C1) | S |
| 0.2 | Demo seeding only when `AURA_ENV=dev`; one-time admin bootstrap; password policy; login throttling and lockout | S |
| 0.3 | Bind Postgres to `127.0.0.1`; real secrets; scram-sha-256; fix RUNNING.md | S |
| 0.4 | **Compliance gate lock:** only compliance clears flags; sign-off bound to a flags + profile hash (C2) | S |
| 0.5 | Revoke app-role write access on `stage_guard` and `users.role`; code-owned guard IDs instead of SQL text; a proper audit insert policy | M |
| 0.6 | Incremental, cached audit verification, taken off the login, metrics and export paths | S |
| 0.7 | Remove the duplicate `deps.py` functions; lifespan handler with graceful shutdown; statement timeouts | S |

### Wave 1 — Controlled pilot, non-UPSI (about 3–5 weeks)
| # | Item | Lens | Effort |
|---|---|---|---|
| 1.1 | **Stage rules per deal type plus maker-checker overrides** (C5) | Domain | M |
| 1.2 | **Notifications:** daily digest, pre-escalation reminders, escalation chain (owner → MD → compliance) | Product | S–M |
| 1.3 | **Human collaboration:** notes and comments, @mentions, owner and due date on diligence items and conditions, a "My work" inbox | Product | M |
| 1.4 | **Mandate economics and partner view:** ticket, fees, probability; pipeline value and fee forecast; stage targets and overdue flags | Domain + Product | M |
| 1.5 | **Real diligence libraries per deal type and sector** (150+ items); blocker waivers need compliance; materiality as a % of deal size | Domain | M |
| 1.6 | **Containerise** API and worker separately; **CI** (pytest, lint-imports, ruff, mypy, alembic check, next build, pip/npm audit, secret scan); a frontend test runner (Vitest plus Playwright smoke tests) (C6) | Eng | M |
| 1.7 | **Backups and DR:** WAL/point-in-time recovery, object-store documents, an offsite HMAC-keyed audit anchor, a restore drill (C6) | Eng | M |
| 1.8 | Responsive layout: sidebar drawer and mobile Decisions | Product | S |
| 1.9 | Quick wins: human-readable errors and labels, a drill-down on the guard-coverage metric, exclude test deals from metrics, admin home | Product | S |

### Wave 2 — Live UPSI mandates (about 4–6 weeks)
| # | Item | Lens | Effort |
|---|---|---|---|
| 2.1 | **SEBI PIT SDD and UPSI register** with an 8-year WORM hold; UPSI-aware export and drafting gates; insider-list export (C3) | Domain | M–L |
| 2.2 | **Compliance control room:** firm-wide read scope, restricted and watch lists, wall-crossing approval, conflict check at intake (C4) | Domain | M |
| 2.3 | **KYC and party module:** beneficial owners, directors, PEP/sanctions, country, listed status; LEI, UDYAM, TAN, ISIN, CKYC with checksums; MCA21 lookup | Domain + Product | M |
| 2.4 | **Rule-derived regulatory flags and statutory conditions precedent** (CCI including the deal-value threshold, SAST, FEMA/Press Note 3, ODI/ECB, NCLT) with deadlines, plus a **post-closing filings stage** (FC-GPR, CHG-1, PAS-3, MGT-14, stamp duty) | Domain | M–L |
| 2.5 | **Outbound gates:** a counterparty-specific executed NDA and a UPSI register entry before sending; store the body hash | Domain | S |
| 2.6 | **DPDP controls:** purpose and retention per record, an erasure workflow reconciled with SDD/PMLA legal hold, a breach log | Domain | M |
| 2.7 | **Session security:** HttpOnly cookie or WebSocket ticket, refresh and revocation, close sockets on deactivation, CSP and security headers | Eng | M |
| 2.8 | **Upload hardening:** magic bytes must match the extension, zip-bomb limits, AV scan, sandboxed parser subprocess | Eng | M |

### Wave 3 — Production scale and AI quality (ongoing)
| # | Item | Lens | Effort |
|---|---|---|---|
| 3.1 | **Real, redacted evaluation corpus** (about 50 packs), held-out split, nightly live evaluations, production corrections fed back into the golden set | AI | M |
| 3.2 | **Rebuild financial extraction** on Docling table grids with deterministic parsing (0.42 → above 0.70); confidence calibration (ECE) | AI | M |
| 3.3 | **Fewer, better decisions:** batch-confirm, auto-confirm when overrides are low, suppress garbage-in | AI + Product | S |
| 3.4 | **Model path:** per-capability routing, a larger GPU model, optional India-region cloud model with UPSI excluded; parallel and streaming intake (5 min → under 1 min) | AI | M–L |
| 3.5 | **Retrieval:** a local cross-encoder reranker, minimum-match full-text search, global search across deals, parties and documents | AI + Product | M |
| 3.6 | **Data room v1:** in-browser preview with page jump from citations, folder index, view watermark; later Q&A and redaction | Product | M–L |
| 3.7 | **Horizontal scale:** a separate worker service; Postgres LISTEN/NOTIFY or Redis for the WebSocket hub, rate limits and a global LLM semaphore; PgBouncer; per-deal audit chains or an outbox | Eng | M–L |
| 3.8 | **Observability:** readiness probes, Prometheus metrics, OTLP traces, JSON logs with request IDs | Eng | S–M |
| 3.9 | **Business analytics:** time-to-close against target, stage SLA, win/lapse reasons, decision response time, AI draft edit distance, adoption funnel | Product | M |

---

## 5. Where to double down
- **Positioning:** "the compliance-safe deal desk for Indian mid-market banks and PE". Lead with on-premise local AI, rule-enforced stages, decision handoffs, walls that bind AI, and intake with citations.
- **SDD as a product:** the hash-chained audit is already most of what SEBI's SDD needs. Wave 2.1 turns it into a compliance product that competitors such as Volody sell on its own.
- **The India moat:** MCA21 lookup, rule-derived Indian regulatory flags, and Indian deal-pack extraction (Schedule III, ITR, GST, CMA, CIBIL).

## 6. Things that should stay human, permanently
- Valuation opinions and fairness views.
- Legal or regulatory conclusions: CCI notifiability, open-offer trigger, FEMA route.
- Waivers, sign-offs and wall-crossing.
- Any decision about which UPSI goes to whom.
- Final disposition of KYC and sanctions checks.
