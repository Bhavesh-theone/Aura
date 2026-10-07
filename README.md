# Aura

A deal-execution workspace for Indian dealmakers. Aura runs a transaction through twelve guarded stages, from first contact to close. Local AI agents do the standardisable work, and every judgement call is handed to a named human.

Everything runs on your machine: local model, local database, no cloud services, no API keys.

![Deal detail](docs/screenshots/deal-detail.png)

## What it does

- **Twelve-stage deal spine.** Each deal moves through the stages ORIGINATED, QUALIFIED, MANDATED, PREPARED, MARKETED, MATCHED, BID/AUCTION, NEGOTIATION, DILIGENCE, DOCUMENTATION, CONDITIONS PRECEDENT and CLOSED. It can also end as LAPSED, WITHDRAWN, REJECTED or ABORTED. Permitted backward moves need a reason code. History is append-only, so cycle time is measured from it alone.
- **Guards as data.** Every forward move is checked against rules stored as database rows, so adding a rule needs no release. Examples: an executed engagement letter, a mandate with a hard criterion, no open diligence blockers, a compliance sign-off on flagged deals. Each check records its result, pass or fail. Only the role a guard names can override it, and only with a written justification.
- **Agents that hand over decisions, not piles of context.** CrewAI agents on a local Ollama model classify documents, extract financials and draft outbound emails. Anything touching money, legal documents or outbound contact, and anything above the materiality cap, becomes a *handoff*. A handoff carries a closed question, options with consequences, a recommendation, and "if you do nothing". Nothing is ever sent automatically. Optionally, an approved email draft can be created in your Gmail through a gated MCP server, after a human approval and pre-send checks; it is off by default (RUNNING.md, "Gmail (outbound email)").
- **Every model call recorded.** Model, prompt template, prompt hash, input, output, tokens and latency. If a run can't be recorded, its output is not used.
- **Tamper-evident audit.** Every change is written to a SHA-256 hash chain plus a local anchor file, so editing or deleting history is detected.
- **Deal walls.** Only members of a deal's team can see it, its documents or its agent runs, admins included. Everyone else gets "not found".
- **Diligence and documents.** Checklists come from templates, and blockers need evidence before they clear. Findings carry ₹ impact. Documents have versions, sensitivity tiers (UPSI is forced to tier 4), an access log and an executed flag. Extractions that feed valuation need confidence of 0.95 or a human sign-off.

| Advance stage: guard checklist | Decisions inbox | Metrics |
|---|---|---|
| ![Advance stage](docs/screenshots/advance-stage-dark.png) | ![Decisions](docs/screenshots/decisions.png) | ![Metrics](docs/screenshots/metrics.png) |

## Workflow walkthrough

One deal, ORIGINATED to CLOSED, as it looks in the portal. Every image is the real UI against the real backend: a fresh `aura.data.live_demo` run (the fictional "Godavari Polymers" debt deal) plus the fictional `AUR-101` to `AUR-117` demo deals where a stage is easier to show on one of those. Nothing is mocked. References are to [docs/PRD-v1.md](docs/PRD-v1.md) features (F1 to F10) and sections.

<details open>
<summary><b>Origination and qualification</b> (steps 1 to 7)</summary>

### 1. Sign in
Everyone signs in with their own account, and everything they decide is recorded in their name. Four roles: dealmaker, analyst, compliance, admin (PRD §3, F10).

![Sign in](docs/screenshots/workflow/01-login.png)

### 2. Dashboard
A dealmaker lands on the pipeline overview: open deals, deals by class, decisions waiting, open diligence blockers, the 12-stage funnel and recent activity (PRD F1, F7, §11).

![Dashboard](docs/screenshots/workflow/02-dashboard.png)

### 3. Deals list
Every deal on the desk, filterable by class, stage and outcome. Only deals whose wall you are on are listed (PRD F1, F10).

![Deals list](docs/screenshots/workflow/03-deals-list.png)

### 4. Open a new deal
A deal always starts at ORIGINATED, and its first history row is written at once. Every later move is guarded and audited (PRD F1).

![New deal](docs/screenshots/workflow/04-new-deal.png)

### 5. Add the client with statutory identifiers
Parties carry CIN, PAN, GSTIN or DIN, format-checked and unique per scheme. A malformed PAN is rejected with a clear message (PRD F3).

![Party with identifiers](docs/screenshots/workflow/05-party-identifiers.png)

### 6. A blocked move
Advance stage lists every guard for the move with its result. With no party carrying an identifier, the T1 guard fails and the move is blocked. Only the role the guard names can override it, and only with a written justification (PRD F2).

![Blocked move](docs/screenshots/workflow/06-guard-blocked.png)

### 7. Guards pass, the deal is QUALIFIED
Once the client has a CIN and PAN, all checks pass and the move goes through. Each check is stored as a guard evaluation row, pass or fail (PRD F2, F1).

![Guards pass](docs/screenshots/workflow/07-guards-pass.png)

</details>

<details>
<summary><b>Mandate and preparation</b> (steps 8 and 9)</summary>

### 8. Executed engagement letter, then MANDATED
Documents carry a version, a sensitivity tier and an executed flag, and the agent's proposed class waits for a human to confirm it. The T2 guard needs an executed engagement letter on file (PRD F5, F2).

![Engagement letter](docs/screenshots/workflow/08-engagement-letter.png)

### 9. Mandate with a hard criterion, then PREPARED
A mandate records what the client asked for as hard, soft and preference criteria. The T3 guard needs at least one hard criterion (PRD F4, F2).

![Mandate](docs/screenshots/workflow/09-mandate-hard-criteria.png)

</details>

<details>
<summary><b>Agents and decisions</b> (steps 10 to 13)</summary>

### 10. Put an agent to work
Classify a document, extract financials or draft an outbound email on the local model. A draft is queued, never sent: it lands in Decisions for a dealmaker (PRD F7, G3).

![Draft email agent](docs/screenshots/workflow/10-draft-email-agent.png)

### 11. A handoff arrives in Decisions
The agent stops and hands over a closed question with options, a recommendation with its confidence, "if you do nothing" with an auto-escalation countdown, and the evidence (PRD F7, SOSPE I7).

![Handoff in the Decisions inbox](docs/screenshots/workflow/11-handoff-decision.png)

### 12. Resolve it with a directive
The dealmaker picks an option, gives reasoning (30+ characters), sets the next checkpoint and escalation trigger, and lists what the agent must not revisit. That directive is handed back and the job continues (PRD F7, §9.5.1).

![Directive form](docs/screenshots/workflow/12-directive-form.png)

### 13. Inspect the exact prompt
Every model call is an agent run: model, template, prompt hash, tokens, latency, confidence and the full prompt. If a run can't be recorded, its output is not used (PRD F8).

![Agent run drawer](docs/screenshots/workflow/13-agent-run-prompt.png)

</details>

<details>
<summary><b>Marketing to negotiation</b> (steps 14 to 16)</summary>

### 14. Counterparties join: MATCHED
Investors, lenders and counsel are attached with their identifiers in a role on the deal. The T5 and T6 guards look for a counterparty with an executed NDA and for two counterparties before bidding (PRD F3, F2).

![Matched parties](docs/screenshots/workflow/14-matched-parties.png)

### 15. Diligence checklist with a blocker and a finding
Entering DILIGENCE creates the checklist from the template. An open blocker stops the move to DOCUMENTATION, and a finding carries its ₹ impact and whether it affects valuation (PRD F6, F2).

![Diligence and findings](docs/screenshots/workflow/15-diligence-finding.png)

### 16. Regression with a reason code
Permitted backward moves are allowed but need a reason code, and history is append-only (PRD F1).

![Stage history with a regression](docs/screenshots/workflow/16-regression-history.png)

</details>

<details>
<summary><b>Diligence and compliance</b> (steps 17 and 18)</summary>

### 17. Regulatory flags and compliance sign-off
A deal with regulatory flags cannot leave DILIGENCE until compliance signs off. The sign-off and its note sit in the rail beside the deal (PRD F2 T9 guard, §3).

![Compliance sign-off](docs/screenshots/workflow/17-compliance-signoff.png)

### 18. Extraction with the 0.95 gate
Figures feed valuation only at confidence 0.95 or higher, or after a named person verifies them. The database refuses an unverified extraction below 0.95 that claims to feed valuation (PRD F5).

![Extraction gate](docs/screenshots/workflow/18-extraction-gate.png)

</details>

<details>
<summary><b>Closing</b> (step 19)</summary>

### 19. Conditions precedent, then CLOSED
The T11 guard needs every condition precedent satisfied or waived. The stage rail shows 12 of 12 complete, and no further move is offered (PRD F2, F1).

![Conditions precedent and closed deal](docs/screenshots/workflow/19-conditions-closed.png)

</details>

<details>
<summary><b>Assurance: audit, metrics and roles</b> (steps 20 to 22)</summary>

### 20. Activity with the audit chain
Every stage move, guard override, decision and agent step is a row in a SHA-256 hash chain, checked against a local anchor. The header shows "Chain verified" and "Anchor matches". The T10 override on the Conditions precedent move is visible with its guard name (PRD F9).

![Activity and audit chain](docs/screenshots/workflow/20-activity-audit-chain.png)

### 21. Success metrics
The six v1 success measures and time in each stage, all computed from the records and not estimated (PRD §11).

![Metrics](docs/screenshots/workflow/21-metrics.png)

### 22. Role gating
Roles are enforced in the API and shown in the UI. An analyst can do the diligence and document work but cannot move a deal between stages (PRD §3, F2).

![Role gating](docs/screenshots/workflow/22-role-gating.png)

</details>

<details>
<summary><b>Dark theme</b></summary>

The same screens in the dark theme: the Decisions inbox with an open handoff, and the blocked move.

| Decisions | Blocked move |
|---|---|
| ![Decisions, dark](docs/screenshots/workflow/23-dark-decisions.png) | ![Blocked move, dark](docs/screenshots/workflow/24-dark-guard-blocked.png) |

</details>

## Tech stack

| Layer | Choice |
|---|---|
| Backend | Python 3.13, FastAPI, SQLAlchemy 2, SQLite, Alembic, uv |
| Architecture | Hexagonal: `core/` (domain, policy, services) imports nothing from the outer layers; enforced by `lint-imports` |
| Agents | CrewAI, local Ollama `qwen3.5:4b`, first-party MCP deals server; a deterministic stub runs when Ollama is down |
| Frontend | Next.js, TypeScript, Radix primitives, lucide icons, self-hosted Inter / Newsreader / JetBrains Mono |
| Design | "Ledger" design system: light-first warm neutrals and dark theme, WCAG AA in both, ⌘K palette, keyboard-first |

## Quick start

Prerequisites: Python 3.13, [uv](https://docs.astral.sh/uv/), Node 18+, [Ollama](https://ollama.com).

```bash
ollama pull qwen3.5:4b

# Backend — migrates and seeds the database on first start
cd backend
uv sync
uv run uvicorn aura.api.main:app --reload --port 8000

# Frontend — in a second terminal
cd frontend
npm install
npm run dev
```

Open <http://localhost:3000>. The backend log should say `Orchestrator: CrewAI on http://localhost:11434`. If it says `StubOrchestrator`, Ollama isn't running: the app still works, but agents return canned output.

Optional: `uv run python -m aura.data.demo` (backend stopped) fills the portal with 17 fictional, fully guarded and audited demo deals plus five more logins, and `uv run python -m aura.data.live_demo` drives a fresh deal through the spine in real time while you watch the portal. See [RUNNING.md](RUNNING.md#demo-data-optional).

### Seeded logins

| User | Password | Role | Can |
|---|---|---|---|
| `bhavesh` | `admin123` | Dealmaker | Move deals, decide handoffs, plus all analyst work |
| `asha` | `analyst123` | Analyst | Upload documents, work diligence, add parties and mandates, run agents |
| `priya` | `compliance123` | Compliance | Manage deal teams, sign off flagged deals, override compliance guards |
| `admin` | `admin123` | Admin | Manage users only — no deal access |

These are development credentials. Change them, and `AURA_JWT_SECRET` in `backend/.env`, before anyone else uses the app.

## Checks

```bash
cd backend
uv run pytest tests -q                       # full suite
uv run lint-imports --config .importlinter   # layering rule
uv run alembic check                         # models and migrations agree
uv run python -m aura.data.verify_audit      # audit hash chain + anchor
uv run python -m aura.evals.run --capability all --orchestrator stub   # golden sets on the deterministic stub (< 2 s)
uv run python -m aura.evals.run --capability classify_document --orchestrator crew --cases cls-015,cls-016   # real-model spot check (needs Ollama; a partial run)
uv run python -m aura.evals.autonomy         # what the autonomy demotion rules would do now (--apply to do it)

cd ../frontend
npm run build                                # must pass with no type errors
```

## Project layout

```
Aura/
├── backend/
│   ├── src/aura/
│   │   ├── core/        # domain, policies (stages, gates, roles), services, ports — no framework imports
│   │   ├── data/        # SQLAlchemy tables, repositories, unit of work, seed, audit verification
│   │   ├── api/         # FastAPI routers, schemas, WebSocket hub
│   │   ├── agents/      # CrewAI crews, recording LLM, gated tools
│   │   ├── mcp/         # first-party deals MCP server
│   │   └── worker/      # background job runner
│   ├── migrations/      # Alembic revisions
│   └── tests/           # unit + integration
├── frontend/
│   ├── app/             # Next.js routes: dashboard, deals, decisions, activity, metrics, admin
│   ├── features/        # per-feature API, hooks, components
│   └── shared/          # design system, shell, API client
└── docs/
    ├── PRD-v1.md               # product requirements for this release
    ├── PRD-v1-conformance.md   # every PRD requirement mapped to code, tests and UI
    └── screenshots/
```

## Documentation

- [RUNNING.md](RUNNING.md) — full operating guide: setup, roles and permissions, API reference, agents, migrations, troubleshooting.
- [docs/PRD-v1.md](docs/PRD-v1.md) — what v1 builds and why, scoped from the SOSPE master specification.
- [docs/PRD-v1-conformance.md](docs/PRD-v1-conformance.md) — requirement-by-requirement status, plus the end-to-end run log.
- [docs/agentic-harness.md](docs/agentic-harness.md) — agent loop mapped to the 13 agentic-harness categories, with an interactive [architecture diagram](docs/architecture/agentic-harness.html), coverage scorecard, what has been implemented and what remains.
- [docs/market-research.md](docs/market-research.md) — comparable real-world platforms, capability matrix, 65-feature benchmark and PRD-v2 candidates.

## Status and limitations

v1 meets PRD-v1: 123 of 128 requirements are done and 5 are partial. One demo deal has been run from ORIGINATED to CLOSED through the UI with live agents.

- **Single machine.** SQLite and a single worker. Deal walls are enforced in the application layer. Postgres with row-level security is the planned upgrade, needed before multiple concurrent users or real unpublished price-sensitive information (UPSI).
- **Small local model.** `qwen3.5:4b` on CPU takes 30 seconds to 3 minutes per agent step and won't always produce a clean tool call. Every agent decision goes to a human, so a weak model costs speed, not correctness.
- **Not production-hardened.** Development secrets and seeded passwords. The audit anchor is a local file, not write-once storage.
- **Out of scope for v1:** matching, auctions, outbound channels, ledgers. See PRD-v1 §7.
