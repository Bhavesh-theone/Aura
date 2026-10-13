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
| Podman | any     | `podman --version` | podman.io (Windows: `C:\Users\<you>\AppData\Local\Programs\Podman\podman.exe`) |

The database runs in a Podman container, so the Podman machine must be running: `podman machine start` (once per boot; `podman machine list` shows it).

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
uv sync --extra docling   # or plain `uv sync` for the light install without Docling
```

That creates `.venv/` and installs everything from `uv.lock`. `--extra docling` adds Docling
(the better PDF parser: layout, table cell grids, OCR; about 1.3 GB with CPU-only torch) — see
[PDF parsing: Docling](#pdf-parsing-docling) for its model folder. Without it PDFs are read by
PyMuPDF. Note that a later plain `uv sync` removes the extra again; `uv run` leaves it alone. The `.env` file is already present with local-only defaults — no editing needed to get started. If you start from `.env.example`, copy it to `backend/.env`: it lists the database passwords and URLs with their development defaults.

### Database (PostgreSQL 16 + pgvector)

Aura uses one PostgreSQL 16 database with the `pgvector` extension, in a Podman container (image `docker.io/pgvector/pgvector:pg16`, container `aura-postgres`, volume `aura-pg-data`) on host port **5433**, bound to 127.0.0.1. `scripts/db.ps1` manages it with Podman directly; it finds `podman` on PATH or in `C:\Users\<you>\AppData\Local\Programs\Podman\`. Run it from the repo root:

```powershell
podman machine start                 # if the Podman machine is not running yet
./scripts/db.ps1 up                  # create or start the container, create roles and extensions
./scripts/db.ps1 status              # container state and readiness
./scripts/db.ps1 psql                # psql as the superuser on the aura database
./scripts/db.ps1 psql -Role aura_app -Database aura_test
./scripts/db.ps1 down                # stop it; the data stays in the aura-pg-data volume
./scripts/db.ps1 reset               # DELETE the volume and start from an empty database
```

The alternative is compose: `podman compose --env-file backend/.env -f infra/postgres/compose.yaml up -d`. Both run the init script `infra/postgres/init/10-aura-roles.sh` (idempotent; `db.ps1 up` re-runs it every time), which creates the roles and the extensions `vector` and `pg_trgm` in `aura` and in `template1` (so the test database gets them too).

**Roles.** The superuser `postgres` is used only for this bootstrap.

| Role | Used by | Can |
| --- | --- | --- |
| `aura_owner` | Alembic, the SQLite import, the test-database setup | Owns the schema; `CREATEDB` (for the test database); `BYPASSRLS`, so the `SECURITY DEFINER` wall-check functions it owns can read the wall tables. Never used by the running app |
| `aura_app` | The API and the worker | DML grants only. Not superuser, not `BYPASSRLS`, owns nothing; no `UPDATE`/`DELETE` on the append-only tables; cannot write `alembic_version` |

**Connection settings** (`backend/.env`, gitignored; the values are local development defaults only):

```bash
AURA_PG_SUPERUSER_PASSWORD=aura_super_dev
AURA_PG_OWNER_PASSWORD=aura_owner_dev
AURA_PG_APP_PASSWORD=aura_app_dev
AURA_DATABASE_URL=postgresql+psycopg://aura_app:aura_app_dev@127.0.0.1:5433/aura          # also the code default
AURA_MIGRATION_DATABASE_URL=postgresql+psycopg://aura_owner:aura_owner_dev@127.0.0.1:5433/aura
```

Use `127.0.0.1`, not `localhost`, in these URLs: on Windows with Podman, `localhost` tries IPv6 `::1` first and stalls about 8 s on every new connection. The driver is psycopg 3 (synchronous) behind a SQLAlchemy 2 `QueuePool`.

### Database migrations (Alembic)

The schema is one Alembic baseline, `backend/migrations/versions/0001_postgres_baseline.py`: BIGINT identity keys, JSONB for every JSON column, TIMESTAMPTZ, `NUMERIC(20,2)` for rupee amounts (`finding.quantified_impact_inr`, `task.materiality_inr`, `agent_run.cost_inr`), CHECK constraints (identifier formats as POSIX regexes), PL/pgSQL triggers that refuse `UPDATE` and `DELETE` on `audit_entries`, `deal_stage_history` and `doc_access_log`, the row-level security policies and the grants. The old SQLite chain `0001`–`0013` is kept in `backend/migrations/sqlite_legacy/` for reference only; it is never run.

Alembic runs as `aura_owner` through `AURA_MIGRATION_DATABASE_URL`. **You normally do nothing:** when that URL is set the API runs `alembic upgrade head` on start; when it is not set the API only checks that the schema is at head and refuses to start if it is not. To drive it by hand:

```bash
cd backend
uv run alembic current              # which revision the database is at
uv run alembic upgrade head         # apply everything pending
uv run alembic downgrade base       # drop the whole schema
uv run alembic check                # fails if the models and the migrations have drifted
```

Never drop the database to change the schema: add a migration.

### Importing an existing SQLite database (once)

If you ran Aura before the move to PostgreSQL, your data is in `backend/aura.db`. With the database up, copy it across before the first API start (the API seeds users and reference data on start, after which the target is no longer empty):

```bash
cd backend
uv run python -m aura.data.migrate_sqlite --from aura.db     # from the repo root: --from backend/aura.db
uv run python -m aura.data.verify_audit                       # prints OK
```

The import first brings the target to the Alembic head (it writes as `aura_owner`, `AURA_MIGRATION_DATABASE_URL` by default). It copies every row and keeps every primary key, then resets the identity sequences. It copies `audit_entries` value for value and re-verifies the hash chain on PostgreSQL, rolling back if any row would not hash identically (the canonical hash normalises `created_at` to naive UTC and sorts JSON keys, so the chain verifies unchanged). It copies the audit anchor when the target database's anchor path differs, and re-writes the stage-guard SQL for the PostgreSQL dialect. It refuses a target that already holds data unless you pass `--force`, which empties it first. `--to <owner URL>` imports into another database, for example a scratch copy. `aura.db` is opened read-only and stays as the backup.

### Frontend

```bash
cd frontend
npm install
```

---

## 3. Running it (three terminals)

The database container must be up first (`./scripts/db.ps1 status`; `./scripts/db.ps1 up` if not). It keeps running in the background.

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

- `Orchestrator now: CrewOrchestrator` — the real agent crew is live.
- `Orchestrator now: StubOrchestrator (Ollama unreachable at ...)` — Ollama isn't running. The portal still works and the handoff loop still runs; you just get deterministic canned output instead of model output. The stub still writes `agent_run` rows (model `stub`).

The choice is made **per segment**, not once at startup: the worker re-checks Ollama at most every 30 s (`AURA_ORCHESTRATOR_HEALTH_TTL_SECONDS`). Start or stop Ollama while the backend runs and the next segment follows. Each segment that runs on the stub because Ollama is down is audited as `orchestrator_fallback`.

**Thinking is off for the crew's model** (`AURA_OLLAMA_THINK=false`, the default). qwen3.5's reasoning mode on the 4B model often used the whole output budget and returned an empty answer ("Invalid response from LLM call - None or empty", a permanent failure) and was 5-10x slower. Set `AURA_OLLAMA_THINK=true` only to experiment. An eval run can share the database with the API and worker (PostgreSQL handles the concurrent writers; audit appends from every process are serialised by a transaction-scoped advisory lock); a real-model eval on a copy of the database is still the safest way to avoid touching autonomy.

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
uv run python -m aura.data.demo                 # into the configured database (aura)
uv run python -m aura.data.demo --db aura_scratch   # or into another database on the same server (created if missing)
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

Every model call (and every stub run) is recorded in `agent_run`, readable at `GET /api/agent-runs?deal_id=` (model, prompt template, prompt hash, latency, tokens, confidence). Each row carries its `segment_id`; once the segment's gate creates a task, its rows also get that `task_id`. If a run cannot be recorded, its output is thrown away and the segment fails.

Gated tool calls the crew attempts on the way (for example `send_email` during a `draft_email` job) are not dropped: they appear in the handoff's `evidence` as `{"type": "additional_gated_attempts", ...}`. None of them ran.

### Gmail (outbound email)

Aura can turn an **approved** `draft_email` into a Gmail draft (default once enabled) or, if you choose, send it. It is **off** until you connect Gmail and switch it on. Agents never send: the crew has no Gmail tool at all, and the email only leaves after a dealmaker approves the draft in Decisions.

**1. Google Cloud console (one time).** In a Google Cloud project: *APIs & Services → Enable APIs* → enable the **Gmail API**. *OAuth consent screen*: User type **External**, publishing status **Testing**, add your Gmail address under **Test users**, and add the scope `https://www.googleapis.com/auth/gmail.compose` (add `gmail.send` only if you will use send mode). *Credentials → Create credentials → OAuth client ID → Desktop app*, download the JSON and save it as **`backend/client_secret.json`** (or point `AURA_GMAIL_CLIENT_SECRET_PATH` at it). It is git-ignored (`client_secret*.json`, `*gmail_token*`); never commit or paste it.

**2. Connect** (opens your browser; sign in as the test user and allow):

```bash
cd backend
uv run python -m aura.mcp.gmail_auth                       # connect with gmail.compose
uv run python -m aura.mcp.gmail_auth --scopes compose,send # only if you want send mode
uv run python -m aura.mcp.gmail_auth --status              # connected account, scopes, expiry (never a token)
uv run python -m aura.mcp.gmail_auth --revoke              # revoke at Google and forget the token
```

The token is kept in the **OS keyring** (Windows Credential Manager, service `aura-gmail`). Only if no keyring backend exists does it fall back to an encrypted file (`backend/data/gmail_token.enc`, key beside it), and the command says so.

**3. Switch it on.** The mode is set **only in `backend/.env`** (or the environment), never through the API, so turning email on needs access to the server:

```bash
AURA_OUTBOUND_MODE=gmail_draft   # off (default) | gmail_draft | gmail_send
AURA_OUTBOUND_DAILY_LIMIT=50     # drafted + sent per UTC day
```

Restart the backend after changing it. **Settings › Integrations** in the portal (admin, dealmaker) shows the connection, the mode and the exact command to connect; `GET /api/integrations/gmail` returns the same (no tokens).

**4. Try it.** On a deal's **Parties** tab add the party's email and mark it primary (dealmaker or analyst), then **Verify** it (dealmaker). Run a `draft_email` job for that party. In **Decisions** the card shows the recipient and what approving does ("Approve → create Gmail draft"). Approve it: within a few seconds the worker creates the draft and the card shows **Gmail draft created ↗** (opens your Gmail drafts). Activity records `outbound_executed`; Metrics shows it under *Outbound email*.

**Testing-mode tokens expire after 7 days.** Google expires refresh tokens of apps in Testing mode after a week. When a refresh fails Aura marks the connection *Reconnect needed* (Integrations page, `--status`), blocks outbound with reason `gmail_reconnect_needed`, and you run the connect command again.

**Safety model.**
- The agent cannot send: `create_gmail_draft` and `send_gmail` are mapped OUTBOUND in `gate_policy`, and they are not among the crew's tools at all. They live on a separate MCP server (`aura.mcp.servers.gmail_server`) that only the worker's outbound step calls (`aura.agents.gmail_mailer.McpGmailMailer`, stdio).
- Human approval, then a re-check: the worker runs the outbound step only for a job resumed after **its own** `draft_email` handoff was resolved with `approve` (a `do_not_revisit` directive from another email never counts). The MCP server checks again, independently, that the approval is resolved, decided `approve`, for exactly this recipient, and not used before; `send_gmail` also refuses unless the mode is `gmail_send`.
- Pre-send checks (each failure is an `outbound_blocked` audit row with its reason, and the job completes noting it): mode not `off`; the approved recipient is still the party's **verified primary** email; not on the **suppression list** (address or domain; **Settings › Suppression**, dealmaker or compliance); the approver is still on the deal's wall; Gmail connected; the **daily cap**.
- Idempotent: one `outbound_message` per handoff (unique key), written and committed as `queued` before Gmail is called, so a retried or resumed segment never sends twice.
- Metrics: `success.outbound_executed` now counts **approved executions**; `outbound.outbound_without_approval` counts executions with no approved handoff behind them and must be **0** (structurally impossible).
- Spans `outbound.check` and `outbound.gmail` carry only the recipient's domain, never the address.

**Hygiene.** If `client_secret.json` was ever shared or pasted anywhere, reset the client secret in the Cloud console (*Credentials → your Desktop client → Reset secret*), download the new JSON, replace the file and reconnect.

### Documents: formats, indexing and search

Every uploaded document is parsed, chunked, embedded locally and stored in `doc_chunk`
(PostgreSQL + pgvector), so it can be searched and retrieved for the agents. Nothing leaves
the machine: parsing is in-process, OCR uses local ONNX models, embeddings come from your
Ollama.

**Supported formats** (upload is refused with **415** otherwise, **413** over the size limit):

| Format | Library | What is kept |
| --- | --- | --- |
| PDF | Docling, else PyMuPDF | **Docling** (when installed; [below](#pdf-parsing-docling)): headings with levels, text, and tables as full cell grids (merged headers, header rows) per page, OCR of scanned pages. **PyMuPDF** (fallback): text per page; lines set larger (1.12x body) or bold and standing alone become headings. A page with (almost) no text layer is **OCR'd** with RapidOCR (`rapidocr_onnxruntime`, models ship in the wheel, works offline): the render is deskewed first and the boxes are grouped into lines. Either way a local vision model can re-read scanned pages |
| DOCX | python-docx | paragraphs, `Heading`/`Title` styles as headings, tables (rows and cells) in document order |
| XLSX / XLSM | openpyxl | each sheet's used range as a table, header row kept (`Sheet: <name>` heading); empty sheets are reported |
| CSV | csv | one table |
| PPTX | python-pptx | per slide (= page): title, text boxes, tables, speaker notes |
| EML | stdlib `email` | headers, plain or HTML body (converted to text), attachments listed **and parsed** when supported (two levels deep) |
| MSG | extract-msg | as EML |
| TXT / MD | — | paragraphs; Markdown `#` lines are headings |

The type comes from the extension and is checked against the magic bytes. A file named `.pdf`
(or `.docx` ...) that is really plain text is read as text with a warning (many demo
placeholders are). A damaged, encrypted or mislabelled file fails **its own** indexing with a
clear error (`index_status: failed`); it never stops the worker. `GET /api/document-formats`
returns the accepted extensions and the limit (the upload dialog shows them).

**Limits** (`backend/.env`): `AURA_MAX_UPLOAD_MB` (25), `AURA_MAX_PAGES` (300 pages or slides),
`AURA_OCR_ENABLED` (true), `AURA_OCR_MAX_PAGES` (50 OCR'd pages per document; later image pages
are reported, not read), `AURA_OCR_MIN_CHARS` (25: a page with fewer extractable characters is
treated as an image). OCR takes about 1-3 s a page on this machine.

#### PDF parsing: Docling

PDFs go through [Docling](https://github.com/docling-project/docling) when it is installed
and its models are present, because it is the only parser that reads financial statements as
tables: on the Project Kaveri test pack (`backend/tests/fixtures/parsing`, see
`docs/research/parser-bakeoff.md`) it gets every cell of the audited P&L and Balance Sheet right
where PyMuPDF produces no grid at all, finds the headings PyMuPDF misses, and reads scans with
far fewer character errors. PPTX, DOCX, XLSX, EML, MSG, CSV and TXT/MD keep their own parsers
(Docling drops speaker notes and sheet names).

**Setup (once, offline afterwards).**

1. `uv sync --extra docling` (Python 3.13 is fine; `rapidocr` is pinned below 3.10, which
   breaks Docling 2.135; on a `MAX_PATH` error set a short cache, e.g.
   `$env:UV_CACHE_DIR = "C:\uvc"`).
2. Put the models in `backend/data/docling-models` (gitignored, ~570 MB): the folders
   `docling-project--docling-layout-heron`, `docling-project--docling-models` (TableFormer) and
   `RapidOcr`. Download them once with `uv run docling-tools models download layout tableformer
   rapidocr -o data/docling-models` (retry if Hugging Face drops the connection), or copy them
   from a machine that has them.
3. Check: `uv run python -c "from aura.ingest.docling_parser import docling_available;
   print(docling_available('data/docling-models'))"` prints `True`. Aura forces
   `HF_HUB_OFFLINE=1` when it builds the converter, so nothing is downloaded at run time.

**Settings** (`backend/.env`):

| Setting | Default | Meaning |
| --- | --- | --- |
| `AURA_PDF_PARSER` | `auto` | `auto`: Docling if the extra and its models are installed, else PyMuPDF. `docling` / `pymupdf` force one |
| `AURA_DOCLING_ARTIFACTS` | `backend/data/docling-models` | the model folder |
| `AURA_DOCLING_MAX_PAGES` | 120 | longer PDFs go straight to PyMuPDF |
| `AURA_DOCLING_TIMEOUT_S` | 600 | per document; a run that does not finish every page falls back |
| `AURA_SCAN_VLM` | `fallback` | vision-model pass over scanned pages: `off`, `fallback`, `always` |
| `AURA_VLM_MODEL` | `qwen3.5:4b` | an Ollama model that accepts images |
| `AURA_VLM_MAX_PAGES` | 5 | scanned pages read by the vision model per document |
| `AURA_VLM_TIMEOUT_S` | 300 | per page (also the wait for a free model slot) |

**Fallback chain.** Docling not installed, models missing, more than
`AURA_DOCLING_MAX_PAGES` pages, an error, or not finished within `AURA_DOCLING_TIMEOUT_S` ->
the PyMuPDF + RapidOCR path, and the document's warnings say why (`Docling failed (...); read
with PyMuPDF instead`). `metadata.parser` on the parsed document records which one ran.

**Vision model on scans.** A page with no text layer is "image-only". With
`AURA_SCAN_VLM=fallback` the vision model reads it (150 dpi, Markdown, temperature 0, thinking
off) when the OCR text on it is thin (under 200 characters), or when the file name says it is a
KYC paper or a board resolution (`kyc`, `resolution`, `pan`, `aadhaar`, `passport`, `signed`,
...), whose handwritten and dense fields OCR loses; `always` reads every image-only page. Its
transcription replaces the OCR text of the page, but a number in it counts only if OCR saw the
same number: otherwise the page's chunks get `needs_review: true` in `doc_chunk.meta` and the
document a warning naming the numbers. Each call takes a slot of the model-call semaphore
(`AURA_MAX_CONCURRENT_LLM_CALLS`), so it queues behind agent calls rather than competing for
the GPU, and is recorded as an `embed_run` row with `kind = 'vlm_page'` (model, latency,
status, characters returned) — not as an `agent_run`, so it does not count against
`AURA_MAX_LLM_CALLS_PER_DAY`. If Ollama is down the OCR text stays, with a warning.

**Performance** (this laptop, CPU, i7 + RTX 3060 for the vision model only):

| Path | Digital PDF page | Scanned page | First document (model load) |
| --- | --- | --- | --- |
| PyMuPDF (+ RapidOCR on scans) | ~5 ms | ~4-7 s (incl. deskew) | ~9 s |
| Docling (CPU) | ~4-5 s (5.5 on table-heavy pages) | ~5-7 s | ~30-40 s |
| Vision model `qwen3.5:4b` (GPU) | — | ~50 s (~80 s cold) | model load in Ollama |

Measured on the Kaveri pack: parsing all 7 documents takes 12 s with PyMuPDF and 39 s with
Docling (cold); the retrieval eval's indexing of both packs 17 s vs 56 s. Results
(`--capability parsing`): table cells 39% -> **100%** (financial statements 0% -> 100%),
row/column fields 42% -> **100%**, key fields 92% -> 95%, headings 89% -> 94%, scanned-page
character error rate 0.148 -> **0.042**; retrieval recall@5 on the 22 Kaveri queries 0.91 ->
**1.00** (Nilgiri unchanged at 1.00).

Peak memory of the worker grows by about 1.6 GB while Docling runs. A 100-page PDF takes
about 7-8 minutes in the background indexer; that is why the page cap and timeout exist, and
why `AURA_INDEX_LEASE_SECONDS` defaults to 1800.

**Parsing eval.** `uv run python -m aura.evals.run --capability parsing [--pdf-parser
pymupdf|docling|both]` parses the Kaveri pack against its ground truth and prints table-cell
accuracy, row/column field checks, key-field recall, heading recall and the character error
rate per document and parser; it passes when the configured parser's mean of table cells,
row/column fields and key fields is at least `AURA_EVAL_THRESHOLD_PARSING` (0.9). The
retrieval eval (`--capability retrieval`) indexes the Kaveri pack next to Nilgiri and includes
its 22 queries.

After switching parsers, reindex what is already stored:
`uv run python -m aura.ingest.backfill --reindex`.

**Indexing.** Upload (and every new version, and **Reindex**) queues the document in
`index_job` (one row per document) and marks it `pending`. A worker thread in the API process
(next to the agent worker, so a long OCR never delays agent jobs) claims jobs with `FOR UPDATE
SKIP LOCKED` and runs: load -> parse -> chunk -> prompt-injection screen -> embed -> replace the
document's chunks in one transaction -> `indexed` (+ `indexed_at`, `chunk_count`, `ocr_used`,
`page_count`, `warnings`).

- Chunking is structure-aware and deterministic: a heading starts a chunk; text windows of
  about `AURA_CHUNK_TARGET_TOKENS` (800, at 4 characters a token) with
  `AURA_CHUNK_OVERLAP_TOKENS` (100) overlap; tables are split by whole rows with the header
  repeated, never mid-row; each chunk keeps `page_from`/`page_to` and `kind` (text|table).
- Screening: every chunk is scored by the injection rules; the text is **kept** and the score
  and matched rules are stored in `doc_chunk.meta` (the document's warnings count flagged
  chunks). Context assembly screens and wraps it again before a model sees it.
- Embeddings: `nomic-embed-text` through Ollama `POST /api/embed` with the nomic task prefixes
  (`search_document: ` / `search_query: `), batches of `AURA_EMBED_BATCH` (16), retries on
  connection errors and 5xx, a 768-dimension check, and the model name on every chunk. Pull it
  once: `ollama pull nomic-embed-text`. `AURA_EMBEDDER=fake` uses deterministic hash vectors
  instead (tests; machines without Ollama).
- Lineage: one `embed_run` row per batch (model, batch size, characters, latency, status,
  trace) plus `index.document` / `embed.batch` spans in the upload's trace. Embeddings are
  **not** `agent_run` rows: those count against the daily model budget and the autonomy
  metrics, which embedding is not part of.
- Reliability: the same `RetryPolicy` as agent segments. A transient failure (Ollama down,
  timeout) is retried with backoff (`AURA_INDEX_MAX_ATTEMPTS` 3, `AURA_INDEX_BACKOFF_SECONDS`
  15) and then dead-lettered; a permanent one (corrupt, unsupported, too many pages) fails at
  once; a claim older than `AURA_INDEX_LEASE_SECONDS` is recovered. Failed documents show
  **Failed** with the reason; **Reindex** (dealmaker or analyst,
  `POST /api/documents/{id}/reindex`) queues them again. A version uploaded while its previous
  one is being indexed supersedes it (the running job's writes are rolled back).
- Audit: `document_indexed`, `document_index_failed`, `index_retry_scheduled`,
  `document_reindex_requested`; the document events also refresh the Documents tab live.

**Backfill** documents uploaded before this existed (or failed ones):

```bash
cd backend
uv run python -m aura.ingest.backfill                 # every document not yet indexed
uv run python -m aura.ingest.backfill --deal 3 --limit 20
uv run python -m aura.ingest.backfill --reindex       # re-index everything (alias --all)
uv run python -m aura.ingest.backfill --queue-only    # just queue; the running API does it
```

**Search.** `GET /api/deals/{id}/search?q=...&k=8` (k up to 50) runs as the caller under
row-level security (a deal off your wall is a 404; another deal's chunks are never returned):

- vector: the query embedded with `search_query: `, nearest chunks by cosine distance
  (pgvector `<=>`, HNSW, `AURA_HNSW_EF_SEARCH` 80 with iterative scans so the deal filter
  still fills the list);
- full text: `websearch_to_tsquery('english', q)` over the chunk's `tsv`; chunks matching every
  term first, then any term, each by `ts_rank_cd`; snippet by `ts_headline`;
- fused with **Reciprocal Rank Fusion** (`AURA_RRF_K` 60) over the top `AURA_SEARCH_CANDIDATES`
  (40) of each list; ties by chunk id. If Ollama is down the search answers from full text only
  (`mode: "fts_only"`, with a warning) rather than failing.

```json
{"query": "CCI approval", "k": 8, "mode": "hybrid", "embedding_model": "nomic-embed-text",
 "took_ms": 41, "warnings": [],
 "results": [{"rank": 1, "chunk_id": 812, "document_id": 57, "filename": "spa_draft.docx",
   "version": 2, "chunk_index": 3, "page_from": null, "page_to": null, "kind": "text",
   "snippet": "Completion is conditional on approval of the Competition Commission of India (⟦CCI⟧ ⟦approval⟧) ...",
   "text": "3. Conditions precedent ...", "score": 0.032787,
   "scores": {"rrf": 0.032787, "vector_rank": 1, "vector_distance": 0.31, "fts_rank": 1, "fts_score": 1.4}}]}
```

The snippet is plain text with matches between `⟦` and `⟧` (render it as text, not HTML).
`GET /api/documents/{id}/chunks?offset=&limit=` pages through a document's chunks (with their
screening score). In the app: **Deal › Documents › Search this deal**.

**Agents use it too.** Context assembly for `classify_document` and `draft_email` now
retrieves related passages with this hybrid search (as the job's user), with page ranges in
the citations; documents not indexed yet fall back to the old keyword (BM25) ranking. An
indexed subject document's excerpt is its parsed text (no more raw PDF bytes).

**Retrieval quality.** `uv run python -m aura.evals.run --capability retrieval` indexes the
fixture deal pack (`backend/tests/fixtures/ingest`, a fictional acquisition: PDF with a scanned
page, DOCX, XLSX, PPTX, EML with a CSV attachment, Markdown, CSV) inside a transaction that is
rolled back, runs the 16 queries of `evals/golden/retrieval.jsonl` and reports recall@5 and MRR
(stored as an `eval_run`, threshold `AURA_EVAL_THRESHOLD_RETRIEVAL` 0.8). It uses Ollama when
`nomic-embed-text` answers (`--embedder fake|ollama` to force).

### Deal intake: auto-filled new deals

**New deal** on the deals page, **⌘K → New deal from documents**, or the **`c`** key opens the intake wizard at `/deals/new` (`/deals/new?intake=<id>` resumes a draft). The old blank form is still reachable as *Quick-create blank deal*.

1. **Documents.** Drop in as many files as you have (the same formats and size limit as deal documents: `GET /api/document-formats`), and optionally a company name, CIN or class hint. Each file uploads with its own progress bar; uploading the same bytes twice is a no-op.
2. **Extraction.** Each file goes through the normal indexing queue (Docling / OCR / vision model for scans, chunking, embeddings) as a *staged* document: a `document` row with no deal and the intake's id. Once every file is indexed the worker's intake thread (`aura.worker.intake`) extracts the fields. Progress arrives live over the WebSocket (to the intake's creator only) with 3-second polling as a fallback. On this machine (CPU, `qwen3.5:4b`, Docling) the six-file Kaveri pack took about 1.5 minutes to index and 3.5 minutes to extract: about 5 minutes from upload to review. You can leave and come back: open drafts are listed above the deals table.
3. **Review.** A two-pane form: fields grouped as Company, Transaction, Parties, Financials, Terms, Regulatory, the class's deal profile (rendered from its JSON Schema) and Mandate criteria. Each field shows its value, a confidence badge and its source (Table, Regex, Model, You); clicking a source opens the cited page with the quoted passage highlighted. Fields below `AURA_INTAKE_CONFIDENCE_THRESHOLD` (0.85) must be accepted or edited; valuation inputs (revenue, EBITDA, PAT, net debt, valuation) need 0.95 or your confirmation; disagreements between documents are shown as choice cards and must be resolved. Every edit autosaves.
4. **Confirm.** Creates the deal through the same `create_deal` service as the blank form (stage `ORIGINATED`, history, wall, audit), the company party (matched by CIN/PAN/GSTIN/LLPIN when it already exists) and the other included parties, a draft mandate with the accepted criteria, the validated profile and the regulatory flags (dealmaker only; an analyst gets a warning). The staged documents, their chunks, index jobs and model runs are re-pointed to the deal in the same transaction - nothing is parsed twice. A deal id is generated (`AUR-0001`, ...) unless you give one.

How extraction works (`aura.core.services.intake_extraction`):

- **Deterministic first.** CIN, PAN, GSTIN and LLPIN by their statutory formats; registered names; `Project <Name>`; tenor, coupon, governing law, ticket size, security, stake; regulatory hints (listing → SEBI, CCI, FEMA, RBI, Press Note 3); and financial line items (*Revenue from operations*, *EBITDA*, *Profit for the year*, *Net debt*) from table grids, in the latest **actual** fiscal-year column (FY25E/projection columns are skipped), with the unit (`₹ crore`, `lakh`, `million`) read from the table, its heading or the document and normalised to whole rupees.
- **Then the local model**, one narrow field group per call (identity, transaction, parties, financials, terms, regulatory, class profile, mandate), skipped for groups the deterministic pass already filled confidently: hybrid search over the intake's chunks with group-specific queries (table chunks first for financials), passages screened for prompt injection and wrapped as untrusted data within `AURA_INTAKE_CONTEXT_CHARS`, `qwen3.5:4b` at temperature 0 with thinking off and Ollama structured output (a JSON Schema per group), JSON repair as a backstop. Prompts are versioned templates `intake.<group>@v1` (pinned in `agents/prompts/manifest.json`).
- **Every value is validated** whoever proposed it: identifier regexes, `₹`/crore/lakh/`Cr`/`L` → INR, enum options, dates (day-first), ranges, and EBITDA/PAT ≤ revenue. A model value that fails validation is dropped with the reason shown on the field.
- **Confidence** = the extractor's (regex 0.86-0.93, table 0.82-0.93, model self-report × a validation multiplier: 1.0 when its quote is in the cited passage and holds the value, 0.85 when only one holds, 0.6 otherwise; model-only values are capped at 0.9), +0.03 per extra document that agrees. Agreeing candidates pool their citations; disagreeing ones become a **conflict**.
- **Reliability.** Extraction never runs in a request. Transient failures (Ollama down) retry with backoff (`AURA_INTAKE_MAX_ATTEMPTS`, `AURA_INTAKE_BACKOFF_SECONDS`); the last attempt runs without the model so you still get the deterministic fields, with a warning. Stale claims are recovered after `AURA_INTAKE_LEASE_SECONDS`. Each model call is an `agent_run` row (archetype `intake_extractor`, template id, `intake_id`; re-pointed to the deal on confirm) - not counted in any agent capability's autonomy metrics.

Privacy: a draft (the `deal_intake` row, its staged documents, chunks, index jobs and model runs) is visible only to its creator, enforced by row-level security (`aura_viewer_intake_ids()`, migration `0004_deal_intake`) and again by the repository; another user gets 404. Discarding a draft deletes its staged rows (the bytes stay in the content-addressed store).

Settings (`AURA_` prefix): `INTAKE_CONFIDENCE_THRESHOLD` (0.85), `INTAKE_LLM` (`ollama` | `off`), `INTAKE_TOP_K` (6), `INTAKE_CONTEXT_CHARS` (5000), `INTAKE_MAX_LLM_CALLS` (24), `INTAKE_MAX_SECONDS` (3600), `INTAKE_LLM_TIMEOUT_S` (300), `INTAKE_MAX_FILES` (30), `EVAL_THRESHOLD_INTAKE` (0.8).

API (all audited, creator-only): `POST /api/intakes` · `GET /api/intakes` (my drafts) · `GET|PATCH|DELETE /api/intakes/{id}` · `POST /api/intakes/{id}/files` (multipart `files`, 413/415) · `DELETE /api/intakes/{id}/files/{file_id}` · `POST /api/intakes/{id}/extract` · `GET /api/intakes/{id}/chunks/{chunk_id}` (cited passage + its page text) · `POST /api/intakes/{id}/confirm` (201 `{deal_id, external_id, name, warnings, intake}`, 409 if already confirmed, 422 `{detail, field_errors}`). `GET /api/metrics` → `evaluation.intake` gives the override rate: the share of auto-filled fields people changed before confirming.

Eval: `uv run python -m aura.evals.run --capability intake [--llm auto|ollama|off]` scores per-field accuracy, citation validity (the cited chunk really holds the value), conflict detection (a doctored revenue figure must raise a conflict) and time on the Kaveri and Nilgiri packs (`evals/golden/intake.json`).

### Retries, dead letters and recovery

The worker claims a segment with `SELECT ... FOR UPDATE SKIP LOCKED` on the oldest runnable queued segment, so two workers can never run the same segment and neither waits for the other. Each claim stamps `claimed_by`, `claimed_at` and counts an attempt.

- **Transient failure** (Ollama refused the connection, a timeout, a 5xx from the model): the segment goes back to `queued` with `not_before` set by exponential backoff (10 s, 20 s, 40 s ...), audited `segment_retry_scheduled`. After `AURA_SEGMENT_MAX_ATTEMPTS` (3) attempts it becomes **`dead_letter`**: the job is `failed`, `last_error` says why, `segment_dead_lettered` is audited and sent over the WebSocket.
- **Permanent failure** (bad model output that fails validation, a run that could not be recorded, a policy refusal, a used-up budget): the segment fails at once with `last_error`, audited `segment_failed` (`"permanent": true`). A refused handoff package keeps its `handoff_rejected` audit row before the segment fails.
- **Inside a segment**, each model call is retried up to `AURA_LLM_MAX_RETRIES` (2) times on a transient error (1 s then 2 s, `AURA_LLM_RETRY_BACKOFF_SECONDS`). Every attempt is its own `agent_run` row with the error, so lineage stays complete.
- **Crash recovery.** A segment left `running` by a crash is found by the sweep that runs at startup and before every claim: once its claim is older than `AURA_SEGMENT_LEASE_SECONDS` (900 s) it is requeued (`segment_recovered`), or dead-lettered if it has no attempts left. Its job's status follows.
- **Budgets.** A segment may make `AURA_MAX_LLM_CALLS_PER_SEGMENT` (12) model calls and run `AURA_MAX_SEGMENT_SECONDS` (600 s); going over fails it (`last_error` names the limit). Across all segments, once `AURA_MAX_LLM_CALLS_PER_DAY` (2000) `agent_run` rows exist since 00:00 UTC, newly claimed segments are deferred to the next UTC day (`not_before`, audited `budget_deferred`).

```bash
# Dead-lettered jobs on deals you can see (dealmaker or analyst)
curl -s localhost:8000/api/jobs/dead-letter -H "Authorization: Bearer $TOKEN"
# Send one round again: its last segment is queued with a fresh attempt count (202; 409 if nothing to retry)
curl -s -X POST localhost:8000/api/jobs/42/retry -H "Authorization: Bearer $TOKEN"
```

**Idempotent submit.** `POST /api/jobs` takes an optional `Idempotency-Key` header (1-255 characters). The same key with the same body within 24 hours returns the original job with **200** and `Idempotent-Replayed: true` instead of creating another; the same key with a different body is **409**. Keys are per user. Without the header nothing changes (202, a new job each time).

| Setting (env) | Default | Meaning |
| --- | --- | --- |
| `AURA_SEGMENT_LEASE_SECONDS` | 900 | A running segment's claim older than this is treated as orphaned |
| `AURA_SEGMENT_MAX_ATTEMPTS` | 3 | Claims before a transient failure dead-letters the segment |
| `AURA_SEGMENT_BACKOFF_SECONDS` | 10 | Base backoff between segment attempts (doubles each time) |
| `AURA_LLM_MAX_RETRIES` | 2 | Retries of one model call on a transient error |
| `AURA_LLM_RETRY_BACKOFF_SECONDS` | 1 | Base backoff between model-call retries |
| `AURA_MAX_LLM_CALLS_PER_SEGMENT` | 12 | Model calls one segment may make |
| `AURA_MAX_SEGMENT_SECONDS` | 600 | Wall-clock time one segment may run |
| `AURA_MAX_LLM_CALLS_PER_DAY` | 2000 | Model calls per UTC day before new segments wait for tomorrow |
| `AURA_ORCHESTRATOR_HEALTH_TTL_SECONDS` | 30 | How long an Ollama health check is trusted |
| `AURA_OLLAMA_THINK` | false | Let the model reason before answering; off sends `reasoning_effort: none` |

The schema for all of this is part of the baseline migration `0001` (it was added in the SQLite-era migration `0011_harness_reliability`).

### Evaluation, autonomy and safety

**Golden sets** are versioned files in `backend/evals/golden/`: `classify_document.jsonl` (24 fictional Indian deal documents, several with uninformative or misleading filenames), `extract_financials.jsonl` (12 snippets; figures in rupees, crore and lakh, two with a figure genuinely absent) and `draft_email.jsonl` (6 briefs scored by rules). Each eval run stores the sha256 of the file it scored, so a changed golden set shows up as a new version.

```bash
cd backend
uv run python -m aura.evals.run --capability all --orchestrator stub        # deterministic, < 2 s
uv run python -m aura.evals.run --capability classify_document --orchestrator crew --limit 5   # the real model (slow)
uv run python -m aura.evals.autonomy             # what the demotion rules would do now
uv run python -m aura.evals.autonomy --apply     # do it (the worker also does this every hour)
```

The runner sends every case through the **real orchestrator path**: the same context assembly (screening, wrapping) a job gets, then `Orchestrator.run`. Every model call is an `agent_run` row with archetype `eval:<role>` and no job or deal. It writes an `eval_run` row plus one `eval_case_result` per case, prints a table, and exits **1** when a capability scores below its threshold (**2** if the database has no eval tables yet: run `alembic upgrade head`). `--orchestrator crew` needs Ollama and never falls back to the stub.

| Capability | Score (pass mark) | Also reported |
| --- | --- | --- |
| `classify_document` | accuracy (`AURA_EVAL_THRESHOLD_CLASSIFY_DOCUMENT`, 0.7) | macro-F1, mean confidence, calibration (accuracy where confidence >= 0.95) |
| `extract_financials` | share of cases with all three figures within tolerance (`..._EXTRACT_FINANCIALS`, 0.7); tolerance per case, the wider of `abs` and `rel` x expected | per-field accuracy, mean confidence, calibration |
| `draft_email` | rubric pass rate (`..._DRAFT_EMAIL`, 0.8). A draft passes when it has a subject, names the party, stays under `max_words`, invents no amount or percentage that is not in the brief, and makes no commitment ("we guarantee", "assured returns", "risk-free" ...) | pass rate per rule |

The stub is a keyword baseline (filename and text phrases, `label: number` with crore/lakh conversion), not a model: its scores say the harness works, not that the model does.

**Override rate** (online feedback): over resolved handoffs in the last 30 days, per capability. A person overrode the agent when they chose `keep` on a class change it proposed, `discard` on an extraction, or `reject` on a draft. `GET /api/evals/override-rates` (wall-filtered) and `GET /api/metrics` → `evaluation.override_rate`.

**Autonomy levels** (`capability_autonomy`, SOSPE 9.6 adapted), one per capability:

| Level | Meaning |
| --- | --- |
| 2 | A confident result may complete without a person (today: an extraction at >= 0.95). Classifications and drafts always go to a person anyway |
| 1 | Every result goes to a person (a confident extraction raises a `policy_required` handoff that says the capability is at level 1) |
| 0 | Switched off. `POST /api/jobs` for it is **409** naming the reason; a queued first segment fails with the same reason. Segments resuming a job a person already approved still finish |

- **Demotion is automatic**, one level at a time, by the worker every `AURA_AUTONOMY_CHECK_INTERVAL_SECONDS` (3600; 0 = off) and by `python -m aura.evals.autonomy --apply`: when the capability's latest eval run on the real model failed its threshold, or when people overrode it more than `AURA_AUTONOMY_MAX_OVERRIDE_RATE` (20%) of at least `AURA_AUTONOMY_MIN_DECISIONS` (20) decisions in `AURA_AUTONOMY_WINDOW_DAYS` (30). Only evidence newer than the last demotion counts, so one bad week drops a level, not to zero. Audited `autonomy_demoted`.
- **Promotion is never automatic**: `POST /api/autonomy/{capability}/promote`, **admin only** (403 otherwise), one level, and only with a passing eval run on the real model from the last 7 days (409 otherwise). Audited `autonomy_promoted`. Stub eval runs count for neither unless `AURA_AUTONOMY_COUNTS_STUB_EVALS=true`.
- `pinned_model` is stored and shown but not yet used to pick the model.

**Prompt-injection screening.** Every piece of document text (the subject document's excerpt, each retrieved chunk) and any tool output the crew reads goes through `core/policy/injection_policy.py` before it reaches a model: zero-width, bidi and control characters are stripped; named rules score the text (`ignore_instructions`, `role_reassignment`, `system_prompt`, `tool_call_json`, `role_tags`, `approval_manipulation`, `base64_blob`, `hidden_unicode`, `excessive_repetition`); the text is wrapped between `<<<UNTRUSTED_DATA>>>` markers with a standing instruction to treat it as data. The score and rules are kept in the segment context (`screening`) and in each run's `input_digest.notes`. At or above `AURA_INJECTION_RISK_THRESHOLD` (0.5) the result **always goes to a person**: a handoff with trigger **`untrusted_content`** whose evidence lists the matched rules and sources, recommending the option that changes nothing (`keep`, `discard`, `reject`), and an `injection_suspected` audit row. The `do_not_revisit` shortcut never applies to it. Once a person approves, the job finishes instead of asking again.

**Context.** A job's context is assembled from the deal's own documents, **as the job's user**, both at submit and again when each segment runs (so a new document version, or a wall change, applies; a document the user can no longer see fails the segment with "no longer visible"). For `classify_document` and `draft_email` the deal's other documents are chunked and ranked with BM25 (standard library, local); the top `AURA_RETRIEVAL_TOP_K` (4) chunks ride along, screened and wrapped, with `citations` (document ids) that also appear on the proposed action. Everything is capped at `AURA_MAX_CONTEXT_CHARS` (6000): the least relevant chunks are dropped first, then the excerpt (`AURA_CONTEXT_EXCERPT_CHARS`, 2000) is truncated; `context_budget` records what was dropped.

**Prompt registry.** Every role prompt is a file `backend/src/aura/agents/prompts/<id>@v<N>.md`, pinned by sha256 in `prompts/manifest.json`. A test fails when a file changes without a version bump: to change a prompt, add `<id>@v<N+1>.md`, pin it, and point `ACTIVE` at it. `agent_run.prompt_template_id` records `<id>@v<N>` (`classify_document@v2` is active; v2 adds the retrieved documents). `GET /api/prompts` lists them.

**Tracing.** A local, OpenTelemetry-shaped tracer (`core/tracing.py`) records spans `job.submit`, `segment.run`, `llm.call` (GenAI attributes `gen_ai.operation.name`, `gen_ai.request.model`, `gen_ai.usage.input_tokens/output_tokens`), `tool.call`, `handoff.create`, `handoff.resolve` (and `eval.run`/`eval.case`) into the `trace_span` table. Nothing is exported anywhere. The OpenTelemetry SDK is not used because `OTEL_SDK_DISABLED=true` (needed to keep CrewAI's telemetry off) would turn it into a no-op. One job is one trace: `POST /api/jobs` returns `trace_id`, segments continue it, each `agent_run` row carries its `trace_id` and `span_id`, and audit rows written inside a span carry `trace_id`/`span_id` in their payload. `GET /api/traces/{trace_id}` (wall-filtered, 404 when nothing is visible). `AURA_TRACING_ENABLED=false` turns it off.

**Rate limits.** `POST /api/jobs`: `AURA_JOB_SUBMITS_PER_MINUTE` (20) per user, a token bucket; over it the answer is **429** with `Retry-After`. Model calls: at most `AURA_MAX_CONCURRENT_LLM_CALLS` (1) at once per process (a local CPU model cannot serve two usefully); a call that waits longer than the segment budget for a slot is a transient error and is retried like any other.

**MCP server.** The standalone stdio deals server (`python -m aura.mcp.servers.deals_server`, acting as `AURA_MCP_USER`) enforces `gate_policy` itself: a gated tool (`send_email`, anything unmapped or over the materiality cap) never runs and answers `{"status": "requires_human_approval", "executed": false, "tool", "category", "message"}`. `add_internal_note` now stores the note (table `deal_note`, as the acting user, behind their walls, audited `note_added`); read them with `GET /api/deals/{id}/notes`.

**A late result is thrown away.** When a worker finishes a segment it first confirms the segment is still claimed by it (same `claimed_by` and attempt count, still running) and holds that row until it commits. If the segment was recovered or re-claimed in the meantime, the late result is discarded and `stale_result_discarded` is audited; its model runs stay on record.

| Setting (env) | Default | Meaning |
| --- | --- | --- |
| `AURA_EVAL_THRESHOLD_CLASSIFY_DOCUMENT` / `_EXTRACT_FINANCIALS` / `_DRAFT_EMAIL` | 0.7 / 0.7 / 0.8 | Pass mark of an eval run |
| `AURA_AUTONOMY_MAX_OVERRIDE_RATE` | 0.20 | Override share above which a capability is demoted |
| `AURA_AUTONOMY_MIN_DECISIONS` | 20 | Decisions needed before the override rate counts |
| `AURA_AUTONOMY_WINDOW_DAYS` | 30 | Window of the override rate |
| `AURA_AUTONOMY_COUNTS_STUB_EVALS` | false | Whether stub eval runs count for demotion and promotion |
| `AURA_AUTONOMY_CHECK_INTERVAL_SECONDS` | 3600 | How often the worker applies the demotion rules (0 = never) |
| `AURA_INJECTION_RISK_THRESHOLD` | 0.5 | Screening score at which a result goes to a person |
| `AURA_MAX_CONTEXT_CHARS` | 6000 | Cap on document text in one model context |
| `AURA_CONTEXT_EXCERPT_CHARS` | 2000 | Characters of the subject document read |
| `AURA_RETRIEVAL_TOP_K` | 4 | Retrieved chunks of the deal's other documents |
| `AURA_JOB_SUBMITS_PER_MINUTE` | 20 | Job submissions per user per minute (0 = off) |
| `AURA_MAX_CONCURRENT_LLM_CALLS` | 1 | Model calls running at once |
| `AURA_TRACING_ENABLED` | true | Record spans in `trace_span` |

Schema: part of the baseline `0001` (added in the SQLite-era `0012_harness_eval_obs`): tables `eval_run`, `eval_case_result`, `capability_autonomy`, `trace_span`, `deal_note`; `trace_id`/`span_id` on `jobs` and `agent_run`; handoff trigger `untrusted_content`.

### Seeing it in the app and the API

- **Partial eval runs.** `--cases ID,ID` (for example `--cases cls-015,cls-016`) scores just those golden cases; `--limit N` takes the first N. Both are stored with `metrics.partial = true`: they appear in the runs list and on **Agent quality**, but autonomy ignores them (they count for neither demotion nor promotion), so a spot check never changes a capability's level. Run the whole set to produce evidence.
- **Job responses** (`POST /api/jobs`, `GET /api/jobs`, `GET /api/jobs/{id}`) carry `attempts`, `phase` (`retrying`, `deferred`, `dead_letter` or null), `next_attempt_at` and `last_error`, all read from the job's latest segment.
- **Agent runs** (`GET /api/agent-runs`, `GET /api/agent-runs/{id}`) carry `trace_id` and `span_id`, the same ids as the job and its spans.
- **Pages.** **Agent quality** (`/quality`) lists eval runs with per-case detail, override rates, each capability's autonomy level and the prompt registry. The **trace viewer** (`/traces/<trace_id>`, reached from a job or an agent run) draws the spans as a waterfall. **Agent jobs** has a dead-letter section with a retry button for each stuck job, and a badge on jobs that are retrying or deferred. **Decisions** styles `untrusted_content` handoffs apart and lists their evidence; a deal's **Notes** show what `add_internal_note` saved; **Metrics** gains reliability, evaluation and security sections.

### API additions

| Endpoint | Notes |
| --- | --- |
| `GET /api/handoffs?status=open\|resolved` | `open` includes escalated. Each item: `id, deal_id, task_id, trigger, context_package, status, created_at, auto_escalate_at` plus `direction, directive, job_id, task_type, resolved_by, resolved_at` |
| `GET /api/handoffs/{id}` | 404 if you are not on the deal's wall |
| `POST /api/handoffs` | Create a task + handoff (dealmaker or analyst). 422 unless a bot-to-human package has `decision_required`, `if_you_do_nothing`, `what_happened`, `evidence`; a human-to-bot handoff needs a full `directive`. Every 422 is also written to the audit trail as `handoff_rejected` with its reason |
| `POST /api/handoffs/{id}/resolve` | Dealmaker, or compliance for `policy_required` (403 otherwise). Body is the directive. 409 if already resolved |
| `GET /api/agent-runs?deal_id=`, `GET /api/agent-runs/{id}` | Model run lineage; the detail view includes the exact prompt and output |
| `GET /api/dashboard/summary` | `open_deals, closed_deals, ended_deals, deals_by_class, deals_by_stage, decisions_waiting, blockers_open, recent_activity` (last 10). `deals_by_stage` counts **every** deal, closed and ended included; `open_deals`, `deals_by_class` and `blockers_open` count open deals (a blocker on a closed or ended deal is no longer open work) |
| `GET /api/metrics` | `stage_dwell: [{stage, n, median_hours, p90_hours}]` (from `deal_stage_history` only; completed stays), `success: {guarded_forward_transitions_pct, runs_traceable_pct, audit_chain_ok, handoff_rejections_422, outbound_executed, deals_closed_end_to_end}` and `reliability: {dead_lettered_segments, retried_segments, recovered_segments, fallback_runs, budget_deferrals}` (counted from the audit trail). Wall-filtered. SM1 is defined over **forward** moves: regressions and exits carry a reason code instead of guards |
| `POST /api/jobs` + `Idempotency-Key` header | Optional. Same key and body within 24 h: the original job, 200, `Idempotent-Replayed: true`. Same key, different body: 409 |
| `GET /api/jobs/dead-letter` | Dealmaker or analyst (403 otherwise), wall-filtered. `[{job: {...job}, segment_id, seq, status: "dead_letter", attempts, last_error, claimed_by, ended_at}]` |
| `POST /api/jobs/{id}/retry` | Dealmaker or analyst. Requeues the job's dead-lettered or failed last segment (audited `segment_retried`); 202 with the job, 404 off-wall, 409 if there is nothing to retry |
| `POST /api/jobs` (0012) | Every job response now carries `trace_id`. 429 + `Retry-After` over the per-user rate; 409 for a capability at autonomy level 0 |
| `GET /api/evals/runs?capability=&limit=`, `GET /api/evals/runs/{id}` | Any signed-in role. `{id, capability, orchestrator, model_id, golden_sha256, n_cases, score, threshold, passed, metrics, started_at, completed_at, created_by}`; the detail adds `cases: [{case_id, passed, score, confidence, expected, actual, detail, agent_run_id, latency_ms, error}]` |
| `GET /api/evals/override-rates` | `[{capability, decisions, overrides, rate, window_days}]`, wall-filtered |
| `GET /api/autonomy` | Any role. `[{capability, level, pinned_model, demoted_at, reason, updated_by, updated_at}]` |
| `POST /api/autonomy/{capability}/promote` | Admin only; 409 without a passing real-model eval run from the last 7 days or when already at 2; 404 for an unknown capability |
| `GET /api/prompts` | `[{template_id, version, ref, role, sha256, active, path}]` |
| `GET /api/traces/{trace_id}` | `{trace_id, spans: [{trace_id, span_id, parent_span_id, name, start, end, duration_ms, attributes, status}]}`, wall-filtered, 404 when none is visible |
| `GET /api/deals/{id}/notes` | `[{id, deal_id, body, author, source, job_id, created_at}]`, 404 off-wall |
| `GET/POST /api/parties/{id}/contacts`, `DELETE /api/parties/{id}/contacts/{cid}`, `POST /api/parties/contacts/{cid}/verify` (0013) | Party email contacts `{id, party_id, name, email, is_primary, verified_at, verified_by, created_by, created_at}`. Read: dealmaker, analyst, compliance; add/remove: dealmaker or analyst; verify: dealmaker. 422 for a malformed address, 409 for a duplicate. Audited `contact_added`, `contact_removed`, `contact_verified` |
| `GET/POST /api/suppression`, `DELETE /api/suppression/{id}` (0013) | Do-not-contact list `{id, kind: email\|domain, value, reason, created_by, created_at}`; dealmaker or compliance; audited `suppression_added`/`suppression_removed` |
| `GET /api/outbound?handoff_id=` (0013) | Wall-filtered outbound log `{id, handoff_id, job_id, deal_id, party_id, to_email, subject, mode, status: queued\|drafted\|sent\|blocked\|failed, gmail_id, gmail_thread_id, error, created_at, completed_at, trace_id}` |
| `GET /api/integrations/gmail` (0013) | Admin or dealmaker. `{mode, connected, account_email, scopes, expires_at, needs_reconnect, storage, daily_limit, sent_today, connect_command, detail}`; never a token. The mode is not settable through the API |
| `GET /api/metrics` (0013) | Adds `outbound: {mode, drafted, sent, blocked, failed, blocked_by_reason, outbound_without_approval}`; `success.outbound_executed` counts approved executions |
| `GET /api/metrics` (0012) | Adds `evaluation: {latest_runs: [{capability, eval_run_id, orchestrator, model_id, score, threshold, passed, completed_at}], override_rate: [...], autonomy: [{capability, level, reason, demoted_at}]}` and `security: {injection_suspected, untrusted_content_handoffs}` |

| `GET/POST/DELETE /api/deals/{id}/members` | Wall membership. POST and DELETE are compliance only, take `{"username": ...}`, and are audited |
| `GET /api/users`, `POST /api/users`, `PATCH /api/users/{id}` | Admin only (see above) |
| `GET/PATCH /api/documents/{id}`, `GET /api/documents/{id}/versions`, `GET .../download` | Metadata (logs a `view`), set `{is_executed?, doc_class?}` (setting a class confirms it), version list, download (logs a `download`). Listing a deal's documents is not logged. Uploading the same filename to a deal adds a version (`current_version`) instead of a new document |
| `GET /api/deals/{id}/extractions`, `POST /api/extractions/{id}/verify` | See above |
| `GET/POST /api/deals/{id}/findings` | `{diligence_item_id, finding_type, description, quantified_impact_inr?, affects_valuation}`; a finding that affects valuation needs an impact |
| `PATCH /api/deals/{id}` | `{regulatory_flags?, profile?, profile_schema_version?}`. Regulatory flags: dealmaker or compliance; a flagged deal cannot leave DILIGENCE until compliance has signed it off. Profile: dealmaker or analyst, the whole profile replaced, validated against the class's schema (422 when invalid), audited `deal_profile_updated` |
| `POST /api/deals`, `GET /api/deals/{id}` | Deal payloads carry `profile` (class-specific deal terms, JSON) and `profile_schema_version`; `POST` accepts an optional `profile`, validated the same way |
| `GET /api/deal-profiles/schemas`, `GET /api/deal-profiles/schemas/{class}` | Any signed-in role. The JSON Schema (draft 2020-12) of each transaction class, for rendering the deal-terms form; 404 for an unknown class |
| `GET/POST /api/deals/{id}/signoffs` | POST `{note}` is compliance only (201) |
| `GET /api/audit/verify` | `{ok, broken_at, anchor: {head_id, head_hash, written_at, ok}}` |

Stage guards: every forward move has guards (T1 party with an identifier, T2 executed engagement letter, T3 a hard mandate criterion, T4 financial statement, T5 counterparty and executed NDA, T6 two counterparties, T7 valuation report, T8 executed term sheet, T9 checklist exists with no open blocker and compliance sign-off where the deal is flagged, T10 executed SPA/SHPA, T11 a condition exists and all are cleared). Each says in plain English what it wants, and the evaluation objects carry `override_role`. A move is made by a dealmaker, **or** by compliance when it supplies `override_justification` and every failing blocking guard names `compliance` (T9, T11); compliance cannot make an ordinary move (403), and a dealmaker cannot override a compliance guard (409). Each successful move links its evaluations to its `deal_stage_history` row.

Mandates follow SOSPE §6.2: `POST /api/deals/{id}/mandates` takes `{title, notes, side: sell|buy|raise|deploy|partner, status?: draft|active|paused|fulfilled|expired|withdrawn (default active), criteria: [{criterion_key, operator: eq|in|gte|lte|between|not_in|contains, value (JSON: a list for in/not_in/between, a number for gte/lte), hardness: hard|soft|preference, weight (0-1, required when soft)}]}`. T3 needs one `hardness = 'hard'` criterion. (Older mandates were converted to this shape by the SQLite-era migration `0010`; the SQLite import copies them as they are.)

**Deal profiles.** Each deal has a `profile` (JSONB, empty by default) with the deal terms that differ by transaction class, checked against a JSON Schema in `backend/src/aura/core/schemas/deal_profile/<CLASS>.v1.json` on create and update. For example DEBT carries `facility_type`, `tenor_months`, `security_package`, `covenants`, `rating`; EQUITY `round_type`, `pre_money_inr`, `instrument`, `cap_table_summary`; MNA `structure`, `stake_pct`, `cci_route`; JV `partner_country`, `fema_route`, `press_note_3`; LPGP `fund_category`, `commitment_inr`, `sebi_aif_category`; HYBRID `instrument`, `conversion_terms`; ALLIANCE `alliance_type`, `exclusivity`, `territory`. The schema files are authoritative. Seeded and demo deals get plausible profiles; re-seeding fills the empty profile of a known demo deal (audited).

**Schema for later phases.** Two tables exist with no code using them yet: `doc_chunk` (document chunks with a generated `tsvector` and a `vector(768)` embedding behind an HNSW index, for hybrid retrieval with Ollama `nomic-embed-text` later; row-level security like documents) and `deal_intake` (draft deals private to their creator until confirmed; no API yet).

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
uv run pytest tests -v              # everything (needs the database container up)
uv run pytest tests/unit -v         # fast — no DB, no network, no model
uv run lint-imports --config .importlinter
uv run alembic check                # models and migrations agree
uv run python -m aura.data.verify_audit   # recompute the audit hash chain and compare it with the anchor: prints OK, or what is wrong, and exits 1
```

The integration tests use a separate database, `aura_test` (override the name with `AURA_TEST_DATABASE`), on the same server. It is dropped, created and migrated once per run as `aura_owner`; the code under test connects as `aura_app`, and every test starts from emptied tables (`TRUNCATE ... RESTART IDENTITY`). Unit tests need no database.

`verify_audit` reads the database named by `AURA_DATABASE_URL` (default the `aura` database on `127.0.0.1:5433`). The same check is available at `GET /api/audit/verify`.

**The audit anchor** (`backend/data/audit_anchor.json`: `head_id`, `head_hash`, `written_at`) is what catches someone deleting the newest audit rows, which a chain cannot show on its own. The API checks the chain against it at start-up, then moves it up to the current head; the worker moves it up about every minute and `verify_audit` does too after a clean check. Verification fails if the chain's head is behind the anchored head, if the anchored row no longer matches, or if any hash breaks. The file `audit_anchor.json` belongs to the database named `aura`; any other database keeps its own, `backend/data/audit_anchor.<database>.json`, so a scratch or test database never compares against the real one. `AURA_AUDIT_ANCHOR_PATH` overrides the location. Writing the anchor to WORM storage is deferred.

Audit rows are appended under a transaction-scoped advisory lock (`pg_advisory_xact_lock`), so the API, the worker and an eval run in separate processes cannot fork the chain. The chain head is read through the `SECURITY DEFINER` function `aura_audit_head()`, so a user who cannot see the newest row's deal still links to it.

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
| Backend fails at start with a connection error on port 5433 | Database container not running | `podman machine start`, then `./scripts/db.ps1 up`; `./scripts/db.ps1 status` to check |
| Every request or test is ~8 s slow to connect | URL uses `localhost` (IPv6 `::1` tried first) | Use `127.0.0.1` in `AURA_DATABASE_URL` and `AURA_MIGRATION_DATABASE_URL` |
| Backend refuses to start: schema not at head | `AURA_MIGRATION_DATABASE_URL` unset, so the API does not migrate | Set it, or run `uv run alembic upgrade head` |
| `migrate_sqlite` says the target is not empty | The API already seeded the new database | Re-run with `--force` (empties the target first) |
| Model output is nonsense / no gate raised | 4B model on CPU is weak                | Known limitation — see the caveat below              |

---

## 8. Known limitations (read before trusting it)

- **The model is small.** `qwen3.5:4b` will not produce a clean tool call every run. When it doesn't propose an action, the job simply completes without raising a gate. The deterministic protection lives in `gate_policy` — agents only *propose* actions. Email leaves only through the gated Gmail integration, after a person approves (off by default; see "Gmail (outbound email)"); nothing moves money.
- **Not production-hardened.** The JWT secret in `.env` is a development default. Change it before anyone else uses this.
- **Single machine.** One local PostgreSQL container and one worker. The database no longer limits concurrency (segment claims use `SKIP LOCKED`, audit appends an advisory lock), but rate limits and the model-call semaphore are still per process.
- **Walls are enforced twice: in the repositories and by PostgreSQL row-level security** (PRD D1). Row-level security is enabled and forced on every deal-scoped table: `deals`, `deal_party`, `deal_stage_history`, `stage_guard_evaluation`, `mandate`, `mandate_criteria`, `document`, `doc_version`, `doc_access_log`, `extraction`, `diligence_item`, `finding`, `deal_signoff`, `condition_precedent`, `deal_note`, `wall`, `wall_member`, `jobs`, `segments`, `task`, `handoff`, `agent_run`, `audit_entries`, `outbound_message`, `trace_span`, `doc_chunk`, `deal_intake`. Every transaction starts with `SET LOCAL aura.viewer = <username>`, from the user bound to the session when a repository is built for it (`aura/data/walls.py`, `bind_viewer`). A row is visible when the viewer is `:system` (the worker, seeding, the SQLite import, audit verification, span export), or when its deal is one the viewer may see: a deal whose wall lists the viewer, or a deal the viewer owns that has no wall yet (the moment inside deal creation before the wall row exists). Rows with no deal stay visible where `deal_id` may be empty; child tables without a `deal_id` follow their parent; a user always sees their own `wall_member` rows; a `deal_intake` row is private to its creator until confirmed, then follows the confirmed deal's wall. The same rule is the `WITH CHECK`, so a write outside the wall fails. With no viewer set, no deal-scoped row is visible. `:system` cannot be a username (usernames allow only letters, digits, `.`, `_`, `-`), and a session that has acted as `:system` stays `:system`. **What this does and does not protect:** the app sets `aura.viewer` itself, so row-level security catches a forgotten filter or a buggy query in the app, not compromised app code. `aura_app` cannot disable row-level security, drop policies, `SET ROLE` or use `row_security = off`. Admins are bound by walls as before. The WebSocket feed is filtered too: an event naming a deal (`entity_changed {kind, deal_id}` and the handoff/job events) reaches only users on that deal's wall, and is dropped if the wall cannot be read.
- **Compliance moves a deal only to override its own guards** (T9, T11), always with a written justification that is stored on the evaluation row and audited.
- **Nothing leaves the machine** unless you connect Gmail and set `AURA_OUTBOUND_MODE` — that is deliberate: local model, local database, no telemetry (CrewAI and OpenTelemetry telemetry are switched off in `.env`).

---

## 9. Where things live

```
Aura/
├── README.md           # product overview and quick start
├── RUNNING.md          # this file
├── backend/            # FastAPI + hexagonal core + agents + MCP
│   └── migrations/     # Alembic: versions/ (PostgreSQL baseline), sqlite_legacy/ (old chain, never run)
├── frontend/           # Next.js portal ("Ledger" design system)
├── scripts/db.ps1      # the PostgreSQL container: up | down | reset | psql | status
├── infra/postgres/     # compose.yaml and the init script that creates roles and extensions
└── docs/
    ├── PRD-v1.md               # what v1 builds and why, with decisions
    ├── PRD-v1-conformance.md   # every requirement mapped to code, tests and UI; E2E run log
    ├── screenshots/            # README images
    └── superpowers/plans/      # the original implementation plans, task by task
```
