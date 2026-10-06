# Aura v1 — Deal Spine PRD

**Status:** Draft for review · **Date:** 2026-10-06
**Parent spec:** SOSPE Master PRD & Technical Architecture v2.0 ("SOSPE")
**Scope in one line:** run one real deal end-to-end, ORIGINATED → CLOSED, on the local Aura stack, with every stage change guarded, evidenced and auditable.

---

## 1. Why this document exists

SOSPE describes a 17-service, multi-region platform delivered over 70+ weeks. Aura today is a single-machine app: FastAPI + SQLite + a local Ollama model + a Next.js portal. Building SOSPE top-down from here would stall.

This PRD picks the **smallest slice of SOSPE that is real and useful**: the deal spine from SOSPE phases P0 and P1, run locally. It reuses SOSPE's vocabulary, stage machine and invariants exactly, so later phases extend this work rather than replacing it.

The SOSPE P1 exit criterion is the v1 goal:

> **One real deal run end-to-end on the platform, from ORIGINATED to CLOSED, with a passing guard evaluation recorded for every stage transition.**

## 2. Where Aura is today

| Area | What exists | Gap against SOSPE |
|---|---|---|
| Jobs & segments | Agent jobs run as segments; a segment pauses for human approval on gated actions | Not tied to a deal stage; no task or handoff model |
| Approval gate | `gate_policy` maps tool names to money / legal / outbound categories and denies anything unmapped (default-deny) | Matches SOSPE I5 in spirit; no materiality limits |
| Deals | `deals` table with a free-text `stage`; the MCP deals server uses **hard-coded deals, not the database** | No stage machine, history, parties or guards |
| Users | `admin` / `member` roles, JWT login | No dealmaker / analyst / compliance roles |
| Audit | Append-only `audit_entries` | Not hash-chained, so tampering can't be detected |
| Model runs | Not persisted | SOSPE C6 requires every inference to be recorded |
| Storage | SQLite, schema built by `create_all`, no migrations | Every schema change today means deleting the database |

## 3. Users in v1

| Role | Maps to SOSPE role | What they do in v1 |
|---|---|---|
| Dealmaker | `dealmaker` / `vp` | Owns deals; approves gated stage transitions; approves outbound drafts |
| Analyst | `analyst` | Uploads documents; works diligence items; runs agent jobs |
| Compliance | `compliance` | Manages deal walls; signs off where a deal carries regulatory flags |
| Admin | `admin` | Manages users and reference data |

One firm, one tenant, a handful of users. Multi-tenancy is out of scope (§7).

## 4. Goals and non-goals

**Goals**
- G1: A deal moves through SOSPE's 12 stages, and can only move when its guards pass.
- G2: Every stage change, guard evaluation, approval and model run can be reconstructed afterwards from stored records alone.
- G3: Agents do the standardisable work (document classification, checklist set-up, drafting) and hand **decisions** to humans, using SOSPE's handoff format.
- G4: Nothing leaves the machine. Local inference only, as today.

**Non-goals for v1**
- Matching, auctions, bid normalisation (SOSPE §8, phase P3)
- Outbound channels beyond drafting; nothing is actually sent (SOSPE §10, P3–P4)
- Ledgers, settlement, the Sovereign Value Fund (SOSPE §5, P4–P5)
- Kafka, Temporal, Kubernetes, multi-region (SOSPE §7)
- Multi-tenancy; vector search; ML entity resolution

## 5. Features

Priority: **P0** = v1 cannot ship without it. **P1** = ships in v1 if time allows.

### F1 — Stage machine (P0)
- Deals use SOSPE's stages: `ORIGINATED … CLOSED`, plus the terminal states `LAPSED`, `WITHDRAWN`, `REJECTED`, `ABORTED` (SOSPE §3.2).
- The permitted backward moves from SOSPE §3.2 are allowed (e.g. DILIGENCE → NEGOTIATION), but each must carry a reason code.
- Every change writes an append-only `deal_stage_history` row. Cycle-time numbers come **only** from this table, never from a deal's last-updated time (SOSPE I6).
- A deal in a terminal state must have an outcome and a close time, and vice versa (enforced by database CHECK constraints).

**Acceptance:** an attempted jump from ORIGINATED to MATCHED is rejected; a regression with no reason code is rejected; editing or deleting a history row fails at the database level.

### F2 — Declarative guards (P0)
- Guards are rows in `stage_guard`, not code (SOSPE §3.3.1). v1 supports one evaluator kind: `sql_predicate`.
- Every transition attempt evaluates all guards for that move and writes one `stage_guard_evaluation` row per guard, whether it passed or failed.
- A guard that errors is treated as **failed**, never as passed.
- A guard can be overridden only by its named role, and an override must include a written justification.
- v1 ships a simplified version of SOSPE's T1–T12 guard set, limited to data Aura actually holds. Examples:
  - T2 → MANDATED: a signed engagement letter is on file.
  - T9 → DOCUMENTATION: zero open diligence items of severity `blocker`.
  - T11 → CLOSED: every condition precedent is satisfied or waived.

**Acceptance:** a new guard is added by inserting a row, with no code change or release; each transition in the demo deal has matching evaluation rows.

### F3 — Parties and identifiers (P0)
- `party` and `party_identifier` tables, with format checks for CIN, PAN, GSTIN and DIN taken from SOSPE §6.1.
- Each identifier scheme + value pair is unique, so the same company can't be entered twice with the same CIN.
- `deal_party` links parties to deals in roles such as buyer, seller, target or investor.
- Duplicates are caught by exact identifier match only. ML entity resolution is deferred.

**Acceptance:** inserting a malformed PAN fails; inserting a second party with an existing CIN fails.

### F4 — Mandates and criteria (P1)
- `mandate` and `mandate_criteria` tables, with SOSPE's `hard` / `soft` / `preference` split (§6.2).
- Not used for matching in v1. It records what the client asked for, and the T3 guard needs at least one hard criterion.

### F5 — Documents (P0)
- A local file store under `backend/data/`, recording a sha256 hash, a document class (SOSPE §6.10 list) and a version for each file.
- Every view or download writes a `doc_access_log` row.
- Documents flagged as containing unpublished price-sensitive information (UPSI) must be marked sensitivity 4 (database CHECK).
- An agent proposes a document class; a human confirms it. Extraction feeding valuation needs confidence ≥ 0.95 or a human sign-off (SOSPE §6.10 constraint).

### F6 — Diligence checklist (P0)
- `checklist_template` and `checklist_item_template` rows, plus `diligence_item` rows per deal, with severities `blocker` / `material` / `standard` / `informational`.
- Entering DILIGENCE creates the deal's checklist from the template for its transaction class.
- An item can't be marked satisfied without evidence documents, or waived without a justification (database CHECK).

### F7 — Tasks and handoffs (P0)
- The current `approvals` table is replaced by SOSPE's `task` + `handoff` model (§6.12).
- A bot-to-human handoff is **rejected with HTTP 422** unless it includes `decision_required` and `if_you_do_nothing` (SOSPE I7, §9.5 schema).
- A human-to-bot handoff requires a directive, including `do_not_revisit` (SOSPE §9.5.1).
- The existing `gate_policy` remains the single place that decides whether an action needs approval, and gains a materiality cap: anything above a configured rupee value is draft-only (autonomy level L1).

**Acceptance:** posting a handoff without `if_you_do_nothing` returns 422; an outbound email proposal always produces a handoff and is never executed.

### F8 — Model run lineage (P0)
- Every Ollama call writes an `agent_run` row: model, version, prompt template ID, prompt hash, input digest, output, confidence (where available), token counts and latency (SOSPE C6).
- Cost is recorded as 0 for local inference, but the column exists so later phases don't need a migration.
- If the run can't be written, its output isn't used.

**Acceptance:** 100% of a sample of runs can be traced from `agent_run` back to their exact prompt.

### F9 — Hash-chained audit (P0)
- Each `audit_entries` row gains `prev_hash` and `row_hash`, where `row_hash = SHA256(prev_hash || canonical_json(row))` (SOSPE §6.14).
- A `verify-audit` command recomputes the whole chain and reports the first broken link.
- Daily anchoring to write-once (WORM) storage is deferred. A local anchor file is written instead.

**Acceptance:** editing any audit row by hand makes `verify-audit` fail at that row.

### F10 — Deal walls, simplified (P1)
- `wall` and `wall_member` tables, with one wall per deal.
- Every read of a deal and its documents is checked against wall membership **in the repository layer** (the data-access code), so no API route can skip the check.
- This is weaker than SOSPE C1, which requires database row-level security plus an OPA policy plus encryption. SQLite has no row-level security; full walls depend on moving to Postgres (§9, D1).

### F11 — MCP deals server reads the database (P0)
- Replace the hard-coded `_DEALS` dictionary in `mcp/servers/deals_server.py` with repository reads, so agents see real deals and real stages.
- Repository reads apply the wall check from F10 once it exists.

## 6. Constraints carried from SOSPE

| SOSPE ref | In v1 | How |
|---|---|---|
| C4 Replayable audit | Yes | F9 hash chain, plus stage history and guard evaluations |
| C6 Model lineage | Yes | F8 `agent_run` |
| C7 Statutory identifiers | Partly | F3 format checks and uniqueness; no live MCA21 or GSTN check |
| C1 / C3 Walls | Partly | F10 in the application layer; full enforcement deferred |
| C2 DPDP personal data | Partly | Data stays on the machine; consent and erasure flows deferred |
| C5 Outreach rules | By omission | v1 sends nothing; outbound actions stop at a draft |
| I5 Autonomy capped by materiality | Yes | `gate_policy` plus materiality cap, deterministic and never decided by the model |
| I6 Cycle time from history only | Yes | F1 |
| I7 Handoff schema | Yes | F7, enforced at the API |
| Local-only | Yes | Existing Aura rule; no cloud model, no API keys |

## 7. Out of scope, mapped to SOSPE phases

| Deferred | SOSPE phase | Reason to defer |
|---|---|---|
| Matching engine, retrieval, scoring | P3 | Needs real deal volume and the deal spine first (SOSPE §10.3.1 rule 1) |
| Auctions, bid normalisation | P3 | Needs a counsel opinion before building (SOSPE C10, R4) |
| Outbound channels, consent, cadence | P3–P4 | Hard stops must exist before the first real send (SOSPE R6) |
| Ledgers (Wing A / Wing B), settlement, fund | P4–P5 | Need closed deals to account for |
| Kafka, Temporal, EKS, OPA | P0–P1 at scale | Single machine; the in-process worker is enough at v1 volume |
| Multi-tenancy, UUIDv7 keys | P0 at scale | One firm; see decision D2 |

## 8. Data model changes

New tables: `party`, `party_identifier`, `deal_party`, `mandate`, `mandate_criteria`, `deal_stage_history`, `stage_guard`, `stage_guard_evaluation`, `document`, `doc_version`, `doc_access_log`, `checklist_template`, `checklist_item_template`, `diligence_item`, `finding`, `condition_precedent`, `task`, `handoff`, `agent_run`, `wall`, `wall_member`.

Changed tables:
- `deals`: gains `transaction_class`, `outcome`, `opened_at` and `closed_at`; `stage` is limited to SOSPE's stage list.
- `audit_entries`: gains `prev_hash` and `row_hash`.
- `approvals`: replaced by `handoff`.

Columns, CHECK constraints and naming follow SOSPE §6. Where a Postgres-only feature is used (arrays, JSONB operators, generated columns), v1 uses the nearest SQLite equivalent.

**This change needs migrations.** Alembic (option C from the earlier schema review) becomes a prerequisite, so the database is migrated rather than deleted and rebuilt.

## 9. Open decisions

| # | Decision | Options | Recommendation |
|---|---|---|---|
| D1 | Database | Stay on SQLite / move to Postgres now | **Decided 2026-10-06: stay on SQLite for v1** (keep the current tech stack). F10 walls are enforced in the repository layer. Postgres row-level security is the upgrade path, needed before multiple concurrent users or the first real UPSI-bearing deal. |
| D2 | Primary keys | Keep integer keys / switch to UUIDv7 | **Decided 2026-10-06: keep integer keys for v1.** Switch to UUIDv7 together with the Postgres move. |
| D3 | Stage names | Map the current free-text stages onto SOSPE's / keep both | Map them once in a migration; keep a single vocabulary. |
| D4 | Model capability | `qwen3.5:4b` local / larger local model | Keep 4B for v1. Agents only classify and draft, and every decision goes to a human, so a weak model costs speed, not correctness. |
| D5 | First real deal | Which deal to use for the end-to-end run | Needs a business owner: pick one live DEBT or ALLIANCE deal, which are the shortest classes in SOSPE §1.2.2. |

## 10. Milestones

Each milestone ends on a test that passes, not on a date (SOSPE §10.3).

| # | Milestone | Features | Exit test |
|---|---|---|---|
| M0 | Migrations and DB decision | Alembic; D1 and D2 settled | Schema upgrade and downgrade both work on a copy of `aura.db` |
| M1 | Stage machine and audit | F1, F2, F9, F11 | Scripted deal reaches CLOSED, with guard rows for every move; `verify-audit` passes, then fails after a hand edit |
| M2 | Parties, documents, diligence | F3, F5, F6 | The T9 guard blocks while a blocker item is open and passes once it is satisfied with evidence |
| M3 | Agents in the loop | F7, F8 | A job proposes a document class and a draft email; both arrive as valid handoffs; `agent_run` traces each one |
| M4 | First real deal | All P0, plus F4 and F10 if done | **SOSPE P1 exit:** one real deal from D5 run end-to-end on Aura |

## 11. Success metrics for v1

| Metric | Target | Measured from |
|---|---|---|
| Stage transitions with a recorded guard evaluation | 100% | `deal_stage_history` joined to `stage_guard_evaluation` |
| Model runs traceable to their prompt | 100% | `agent_run` |
| Audit chain verification | 100% pass | `verify-audit` |
| Handoffs missing required fields that reached a human | 0 | API 422 log |
| Outbound actions executed without human approval | 0 | `task` / `handoff` / audit |
| Real deals run end-to-end | ≥ 1 | M4 |
