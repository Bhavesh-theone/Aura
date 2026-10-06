# Running Aura

Everything runs on your machine. No cloud services, no API keys, no internet required after setup.

> **Status:** verified end to end on 2026-10-06. A deal was taken from ORIGINATED to CLOSED through the UI with the live CrewAI + `qwen3.5:4b` agents; the run log is in [docs/PRD-v1-conformance.md](docs/PRD-v1-conformance.md). Anything here that fails is a bug to fix, not something to work around.

---

## 1. Prerequisites

| Tool   | Version | Check                | If missing                                                     |
| ------ | ------- | -------------------- | -------------------------------------------------------------- |
| Python | 3.13    | `python --version` | Installed                                                      |
| uv     | 0.12+   | `uv --version`     | `powershell -c "irm https://astral.sh/uv/install.ps1 \| iex"` |
| Node   | 18+     | `node --version`   | nodejs.org                                                     |
| Ollama | any     | `ollama --version` | Installed                                                      |

Confirm the model is present:

```bash
ollama list
```

You need **`qwen3.5:4b`** in that list. If it is missing:

```bash
ollama pull qwen3.5:4b
```

> Ignore `qwen3.6:latest` if you see it — at 23 GB it exceeds this machine's 13.8 GB of RAM and cannot run. `qwen3.5:4b` is the correct model here.

---

## 2. First-time setup

### Backend

```bash
cd backend
uv sync
```

That creates `.venv/` and installs everything from `uv.lock`. The `.env` file is already present with local-only defaults — no editing needed to get started.

### Database migrations (Alembic)

The schema is versioned in `backend/migrations/versions/` (`0001` baseline through `0010`). **You normally do nothing:** the API runs `alembic upgrade head` on every start, so an existing `backend/aura.db` is upgraded in place (its approvals become handoffs, existing deals get a wall with their owner on it, `member` users become analysts, the admin user `bhavesh` becomes a dealmaker, documents get version rows, checklist items are grouped under templates). `0009` refuses to run, changing nothing, if a stored identifier is malformed: fix the named rows first. To drive it by hand:

```bash
cd backend
uv run alembic current              # which revision the database is at
uv run alembic upgrade head         # apply everything pending
uv run alembic downgrade -1         # step back one revision (every step has a downgrade)
uv run alembic check                # fails if the models and the migrations have drifted
```

Point any of these at a scratch database with `AURA_DATABASE_URL=sqlite:///C:/path/scratch.db`. Never delete `aura.db` to change the schema: add a migration.

### Frontend

```bash
cd frontend
npm install
```

---

## 3. Running it (three terminals)

### Terminal 1 — Ollama

```bash
ollama serve
```

Leave it running. If Ollama is already running as a background service, skip this — `ollama list` working means it's up.

### Terminal 2 — Backend API

```bash
cd backend
uv run uvicorn aura.api.main:app --reload --port 8000
```

Watch the startup log for the orchestrator line:

- `Orchestrator: CrewAI on http://localhost:11434` — the real agent crew is live.
- `Orchestrator: StubOrchestrator (Ollama unreachable...)` — Ollama isn't running. The portal still works and the handoff loop still runs; you just get deterministic canned output instead of model output. The stub still writes `agent_run` rows (model `stub`).

Verify: [http://localhost:8000/api/health](http://localhost:8000/api/health) returns `{"status":"ok"}`
API docs: [http://localhost:8000/docs](http://localhost:8000/docs)

### Terminal 3 — Frontend

```bash
cd frontend
npm run dev
```

Open [http://localhost:3000](http://localhost:3000)

**Login** (seeded automatically on first backend start; re-seeding is idempotent):

| User | Password | Role | Can |
| --- | --- | --- | --- |
| `bhavesh` | `admin123` | dealmaker | Move deals between stages (and override a guard that names `dealmaker`), resolve handoffs, set regulatory flags, plus all analyst work |
| `asha` | `analyst123` | analyst | Upload documents, edit diligence items / conditions / findings, create parties and mandates, run agent jobs, verify extractions. **Cannot** move a deal, resolve a handoff or sign off |
| `priya` | `compliance123` | compliance | Add and remove wall members, sign deals off, set regulatory flags, resolve `policy_required` handoffs, and move a deal **only as an override** of guards that name `compliance` (see below). **Cannot** make an ordinary move or edit deal data |
| `admin` | `admin123` | admin | Manage users (`/api/users`) and nothing else. No deal powers: walls bind admins too |

Permissions are enforced in the core services, not just the routes: the same checks hold for the API, the worker and the tests. Role is checked before the wall, so a role that may not do something gets **403**; a deal you are not on the wall for is **404**, as if it did not exist.

`bhavesh`, `asha` and `priya` are members of the seeded deals D-001 and D-002. A deal created later starts with its creator **and every active compliance user** on its wall (compliance manages walls, and could not reach one it is not on); compliance then adds the rest:

```bash
curl -s -X POST localhost:8000/api/deals/1/members -H "Authorization: Bearer $PRIYA_TOKEN" \
  -H 'Content-Type: application/json' -d '{"username":"asha"}'
```

Re-seeding never adds back someone who was removed from a wall on purpose.

### Users and roles (admin only)

```bash
curl -s localhost:8000/api/users -H "Authorization: Bearer $ADMIN_TOKEN"          # list
curl -s -X POST localhost:8000/api/users -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"username":"ravi","password":"at-least-8-chars","role":"analyst"}'          # 201
curl -s -X PATCH localhost:8000/api/users/5 -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H 'Content-Type: application/json' -d '{"role":"compliance","active":true}'
```

Roles are `admin`, `dealmaker`, `analyst`, `compliance`. An inactive user cannot log in and an existing session stops working at once. The last active admin cannot be demoted or deactivated.

Admins are bound by walls too: an admin must be on a deal's wall to see it.

### Demo data (optional)

To make the portal look like a working deal desk, build the demo dataset once:

```bash
cd backend
uv run python -m aura.data.demo                 # into backend/aura.db
uv run python -m aura.data.demo --db C:/tmp/scratch.db   # or into another SQLite file
uv run python -m aura.data.demo --with-agents   # two of the jobs run on the live CrewAI + Ollama crew (slow)
```

Stop the backend first when building into the database it is serving (the demo writes with its own clock, see below). It creates 17 fictional deals (`AUR-101` … `AUR-117`) covering all seven classes and every stage, including CLOSED, LAPSED, WITHDRAWN, REJECTED and ABORTED, with parties carrying valid-format CIN/PAN/GSTIN/LLPIN, mandates, generated placeholder PDFs, worked diligence, ₹ findings, conditions precedent, regulatory flags with compliance sign-offs, two regressions with reason codes, a blocked move, guard overrides with justifications, 5 open decisions (one escalated) and 10 resolved ones. Every entity is invented.

Everything is created **through the core services as the user who would do it**, so stage history, guard evaluations, walls, the audit hash chain and the metrics are real. Only time is simulated: the services read "now" from a clock seam (`aura/core/clock.py`, system clock by default), and the builder replays about six months of business days in one chronological order. Agent work runs on the stub orchestrator and is recorded as model `stub`; `--with-agents` runs two jobs on the real crew instead. Re-running is safe: deals are keyed by `external_id`, users by username, and deals that are not the demo's (D-001, D-002, …) are never touched. `verify_audit` prints OK afterwards.

It adds these logins next to the seeded ones (all on the demo walls they work on; `bhavesh`, `asha` and `priya` sit on most deals):

| User | Password | Role |
| --- | --- | --- |
| `vikram` | `dealmaker123` | dealmaker |
| `neha` | `dealmaker123` | dealmaker |
| `rohan` | `analyst123` | analyst |
| `kavya` | `analyst123` | analyst |
| `meera` | `compliance123` | compliance |

### Watch a live workflow

With the backend and frontend running, drive one fresh deal through the spine in real time, through the public API only:

```bash
cd backend
uv run python -m aura.data.live_demo            # 8 s between steps
uv run python -m aura.data.live_demo --fast     # 2 s between steps
```

Log in as **bhavesh** and open three windows side by side: the deal page the script prints (`/deals/<id>`), **Decisions** and **Activity**. They update live over the WebSocket; no reload needed. The story ("LIVE — Godavari Polymers ₹60 Cr senior secured debt", a new `LIVE-<timestamp>` deal each run): bhavesh opens the deal, priya staffs the wall, a first move is **blocked** by a guard, asha adds the client with its identifiers and uploads documents, bhavesh advances stage by stage, the agents classify a document and draft an email (on CrewAI + Ollama if the backend runs it, otherwise the stub), asha works diligence and raises a finding, priya flags and signs off, and the deal closes.

When an agent hands over a decision the script prints *"Waiting for your decision in Decisions inbox (log in as bhavesh)"*: resolve it yourself and watch the job continue, or it resolves it as bhavesh after `--auto-resolve-after` seconds (default 120). Flags: `--pace S`, `--fast`, `--until STAGE` (stop at a stage), `--auto-resolve-after S`, `--wait-for-human` (never auto-resolve), `--api URL` (default `http://localhost:8000`). Ctrl+C stops between API calls and leaves the deal valid at the stage it reached.

---

## 4. Using it

1. **Submit a job** — give the agents a brief, e.g. *"draft an intro email to Ravi Menon about deal D-002"*.
2. **Wait.** On CPU-only inference a segment takes **30 seconds to 3 minutes**. This is expected, not a hang. The UI shows segment-level progress.
3. **Decisions waiting (handoffs).** The agents stop when they propose anything touching money, legal documents, outbound communication, a tool the gate policy does not know, or anything worth more than the materiality cap (default 5 crore, `AURA_MATERIALITY_CAP_INR`). Each stop is a **handoff**: a question, 2-5 options with consequences, the policy's recommendation, and what happens if nobody answers. Open handoffs not answered by their `auto_escalate_at` are marked `escalated` (still open for a human).
4. **Resolve it** (a dealmaker; compliance may also resolve handoffs whose trigger is `policy_required`; everyone else gets 403). The directive needs `decision` (one of the offered option ids), `reasoning` (30+ characters), `new_constraints.do_not_revisit` and `next_checkpoint {condition, escalate_if}`. `approve` starts a fresh segment that continues the job; `reject` ends it. Resolving twice returns 409.
5. **Activity** shows the append-only audit trail of everything that happened (only entries for deals you are on the wall for).

### Agents on a deal

A job can carry a `deal_id` (you must be on its wall) and one of three capabilities. Drafts and classifications end in a handoff; nothing is ever sent.

```bash
# Propose a class for an uploaded document; a human confirms it (sets class_confirmed)
{"inputs":{"capability":"classify_document","document_id":12},"deal_id":1}
# Draft an outbound email to a party on the deal; always a handoff, never sent
{"inputs":{"capability":"draft_email","party_id":3,"brief":"Introduce the mandate"},"deal_id":1}
# Read revenue / EBITDA / net debt out of a document into an extraction
{"inputs":{"capability":"extract_financials","document_id":12},"deal_id":1}
```

An extraction is stored with `feeds_valuation: false`. Below 0.95 confidence it also raises a `confidence_below_threshold` handoff (options `verify` / `discard`); verifying (through the handoff or `POST /api/extractions/{id}/verify`, dealmaker or analyst) records who vouched and flips `feeds_valuation`. The database refuses an unverified extraction under 0.95 that claims to feed valuation.

**Agent tools are gated before they run.** The crew gets the deals MCP tools (`get_deal_status`, `list_deals`, `add_internal_note`, `send_email`). Every call passes through `gate_policy` first: reads and internal writes execute as the submitting user; anything gated (`send_email`, unmapped tools, anything over the materiality cap) is **never executed**. The attempt becomes a task and handoff and the segment pauses. If an outbound action were ever executed it would be recorded as `outbound_executed`; the metrics endpoint shows that count, which must stay 0.

**do_not_revisit.** When a resolved handoff on a deal has `new_constraints.do_not_revisit` listing a task type, a later proposal of that task type on the same deal creates no handoff: the earlier decision is applied to the job (approve continues it, anything else ends it) and `handoff_skipped_per_directive` is audited.

Every model call (and every stub run) is recorded in `agent_run`, readable at `GET /api/agent-runs?deal_id=` (model, prompt template, prompt hash, latency, tokens, confidence). If a run cannot be recorded, its output is thrown away and the segment fails.

### API additions

| Endpoint | Notes |
| --- | --- |
| `GET /api/handoffs?status=open\|resolved` | `open` includes escalated. Each item: `id, deal_id, task_id, trigger, context_package, status, created_at, auto_escalate_at` plus `direction, directive, job_id, task_type, resolved_by, resolved_at` |
| `GET /api/handoffs/{id}` | 404 if you are not on the deal's wall |
| `POST /api/handoffs` | Create a task + handoff (dealmaker or analyst). 422 unless a bot-to-human package has `decision_required`, `if_you_do_nothing`, `what_happened`, `evidence`; a human-to-bot handoff needs a full `directive`. Every 422 is also written to the audit trail as `handoff_rejected` with its reason |
| `POST /api/handoffs/{id}/resolve` | Dealmaker, or compliance for `policy_required` (403 otherwise). Body is the directive. 409 if already resolved |
| `GET /api/agent-runs?deal_id=`, `GET /api/agent-runs/{id}` | Model run lineage; the detail view includes the exact prompt and output |
| `GET /api/dashboard/summary` | `open_deals, closed_deals, ended_deals, deals_by_class, deals_by_stage, decisions_waiting, blockers_open, recent_activity` (last 10). `deals_by_stage` counts **every** deal, closed and ended included; `open_deals`, `deals_by_class` and `blockers_open` count open deals (a blocker on a closed or ended deal is no longer open work) |
| `GET /api/metrics` | `stage_dwell: [{stage, n, median_hours, p90_hours}]` (from `deal_stage_history` only; completed stays) and `success: {guarded_forward_transitions_pct, runs_traceable_pct, audit_chain_ok, handoff_rejections_422, outbound_executed, deals_closed_end_to_end}`. Wall-filtered. SM1 is defined over **forward** moves: regressions and exits carry a reason code instead of guards |
| `GET/POST/DELETE /api/deals/{id}/members` | Wall membership. POST and DELETE are compliance only, take `{"username": ...}`, and are audited |
| `GET /api/users`, `POST /api/users`, `PATCH /api/users/{id}` | Admin only (see above) |
| `GET/PATCH /api/documents/{id}`, `GET /api/documents/{id}/versions`, `GET .../download` | Metadata (logs a `view`), set `{is_executed?, doc_class?}` (setting a class confirms it), version list, download (logs a `download`). Listing a deal's documents is not logged. Uploading the same filename to a deal adds a version (`current_version`) instead of a new document |
| `GET /api/deals/{id}/extractions`, `POST /api/extractions/{id}/verify` | See above |
| `GET/POST /api/deals/{id}/findings` | `{diligence_item_id, finding_type, description, quantified_impact_inr?, affects_valuation}`; a finding that affects valuation needs an impact |
| `PATCH /api/deals/{id}` | `{regulatory_flags}` (dealmaker or compliance). A flagged deal cannot leave DILIGENCE until compliance has signed it off |
| `GET/POST /api/deals/{id}/signoffs` | POST `{note}` is compliance only (201) |
| `GET /api/audit/verify` | `{ok, broken_at, anchor: {head_id, head_hash, written_at, ok}}` |

Stage guards: every forward move has guards (T1 party with an identifier, T2 executed engagement letter, T3 a hard mandate criterion, T4 financial statement, T5 counterparty and executed NDA, T6 two counterparties, T7 valuation report, T8 executed term sheet, T9 checklist exists with no open blocker and compliance sign-off where the deal is flagged, T10 executed SPA/SHPA, T11 a condition exists and all are cleared). Each says in plain English what it wants, and the evaluation objects carry `override_role`. A move is made by a dealmaker, **or** by compliance when it supplies `override_justification` and every failing blocking guard names `compliance` (T9, T11); compliance cannot make an ordinary move (403), and a dealmaker cannot override a compliance guard (409). Each successful move links its evaluations to its `deal_stage_history` row.

Mandates follow SOSPE §6.2: `POST /api/deals/{id}/mandates` takes `{title, notes, side: sell|buy|raise|deploy|partner, status?: draft|active|paused|fulfilled|expired|withdrawn (default active), criteria: [{criterion_key, operator: eq|in|gte|lte|between|not_in|contains, value (JSON: a list for in/not_in/between, a number for gte/lte), hardness: hard|soft|preference, weight (0-1, required when soft)}]}`. T3 needs one `hardness = 'hard'` criterion. Migration `0010` converts older mandates (kind→hardness, attribute→criterion_key, operator `eq`, value kept as a JSON string, side from the deal's class, status `active`).

`/api/approvals` no longer exists. Stage-guard evaluations (preview, transition 200 and 409) now include a plain-English `description`.

---

## 5. Verifying it works from the command line

```bash
# Log in and capture a token
TOKEN=$(curl -s -X POST localhost:8000/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"bhavesh","password":"admin123"}' \
  | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

# Submit a job
curl -s -X POST localhost:8000/api/jobs \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"inputs":{"brief":"draft an intro email to Ravi Menon about deal D-002"}}'

# Wait for the worker, then see what needs a decision
sleep 30
curl -s "localhost:8000/api/handoffs?status=open" -H "Authorization: Bearer $TOKEN"

# Approve it (a dealmaker; bhavesh is one)
curl -s -X POST localhost:8000/api/handoffs/1/resolve \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"decision":"approve","reasoning":"The draft is accurate and the tone is right.","new_constraints":{"do_not_revisit":[]},"next_checkpoint":{"condition":"Reply received","escalate_if":"No reply in 7 days"}}'

# The job should reach "complete"
sleep 30
curl -s localhost:8000/api/jobs/1 -H "Authorization: Bearer $TOKEN"
```

---

## 6. Tests

```bash
cd backend
uv run pytest tests -v              # everything
uv run pytest tests/unit -v         # fast — no DB, no network, no model
uv run lint-imports --config .importlinter
uv run alembic check                # models and migrations agree
uv run python -m aura.data.verify_audit   # recompute the audit hash chain and compare it with the anchor: prints OK, or what is wrong, and exits 1
```

`verify_audit` reads the database named by `AURA_DATABASE_URL` (default `backend/aura.db`). The same check is available at `GET /api/audit/verify`.

**The audit anchor** (`backend/data/audit_anchor.json`: `head_id`, `head_hash`, `written_at`) is what catches someone deleting the newest audit rows, which a chain cannot show on its own. The API checks the chain against it at start-up, then moves it up to the current head; the worker moves it up about every minute and `verify_audit` does too after a clean check. Verification fails if the chain's head is behind the anchored head, if the anchored row no longer matches, or if any hash breaks. A database other than the default keeps its anchor beside its own file (`<db>.audit_anchor.json`), so a scratch copy never compares against the real one; `AURA_AUDIT_ANCHOR_PATH` overrides the location. Writing the anchor to WORM storage is deferred.

The `lint-imports` command is the important one. It enforces the architectural rule that `core/` imports nothing from `data/`, `api/`, `worker/`, `mcp/`, or `agents/` — and no FastAPI, SQLAlchemy or pydantic. If it reports **BROKEN**, a layering violation has crept in; fix the import rather than editing the contract.

Frontend:

```bash
cd frontend
npm run build      # must pass with no type errors
```

---

## 7. Troubleshooting

| Symptom                                   | Cause                                  | Fix                                                   |
| ----------------------------------------- | -------------------------------------- | ----------------------------------------------------- |
| `uv` not recognised                     | Terminal opened before uv install      | Close the terminal completely and open a new one      |
| Log says`StubOrchestrator`              | Ollama not reachable                   | Start`ollama serve`, restart the backend            |
| Job sits in`pending` forever            | Worker thread died                     | Restart the backend; check its log for a traceback    |
| Job takes minutes                         | **Normal** — CPU-only inference | Not a bug: a 4B model on CPU takes 30 s – 3 min per step |
| Frontend shows "cannot reach API"         | Backend not running on :8000           | Start terminal 2                                      |
| Handoff resolve returns 409               | Already resolved                       | Each handoff can be resolved once, by design          |
| Handoff create/resolve returns 422        | Incomplete package or directive        | The response names the missing field                  |
| A deal or document returns 404            | You are not on the deal's wall         | A compliance user on the wall adds you (`POST /api/deals/{id}/members`) |
| Any write returns 403                     | Your role may not do that              | See the roles table in section 3; `admin` has no deal powers |
| `lint-imports` BROKEN                   | Layering violation                     | Remove the offending import; don't relax the contract |
| Model output is nonsense / no gate raised | 4B model on CPU is weak                | Known limitation — see the caveat below              |

---

## 8. Known limitations (read before trusting it)

- **The model is small.** `qwen3.5:4b` will not produce a clean tool call every run. When it doesn't propose an action, the job simply completes without raising a gate. The deterministic protection lives in `gate_policy` — but in v1 agents only *propose* actions; nothing actually sends email or moves money yet.
- **Not production-hardened.** The JWT secret in `.env` is a development default. Change it before anyone else uses this.
- **Single machine, single user at a time.** SQLite plus a serialized worker. Concurrent agent runs need Postgres first.
- **Walls are application-level.** Every deal read goes through the repositories, which filter by wall membership, but SQLite has no row-level security. The WebSocket feed is filtered too: an event naming a deal (`entity_changed {kind, deal_id}` and the handoff/job events) reaches only users on that deal's wall, and is dropped if the wall cannot be read. Real walls need Postgres (PRD D1).
- **Compliance moves a deal only to override its own guards** (T9, T11), always with a written justification that is stored on the evaluation row and audited.
- **Nothing leaves the machine** — that is deliberate: local model, local database, no telemetry (CrewAI and OpenTelemetry telemetry are switched off in `.env`).

---

## 9. Where things live

```
Aura/
├── README.md           # product overview and quick start
├── RUNNING.md          # this file
├── backend/            # FastAPI + hexagonal core + agents + MCP
├── frontend/           # Next.js portal ("Ledger" design system)
└── docs/
    ├── PRD-v1.md               # what v1 builds and why, with decisions
    ├── PRD-v1-conformance.md   # every requirement mapped to code, tests and UI; E2E run log
    ├── screenshots/            # README images
    └── superpowers/plans/      # the original implementation plans, task by task
```
