# Running Yuki OS Portal

Everything runs on your machine. No cloud services, no API keys, no internet required after setup.

> **Status:** written against the designed commands. Steps marked ⚠️ have not been executed end-to-end yet — the build was still in progress when this was written. Anything that fails is a bug to fix, not something to work around.

---

## 1. Prerequisites

| Tool   | Version   | Check                | If missing                                          |
| ------ | --------- | -------------------- | --------------------------------------------------- |
| Python | 3.13      | `python --version`   | Installed                                           |
| uv     | 0.12+     | `uv --version`       | `powershell -c "irm https://astral.sh/uv/install.ps1 \| iex"` |
| Node   | 18+       | `node --version`     | nodejs.org                                          |
| Ollama | any       | `ollama --version`   | Installed                                           |

Confirm the model is present:

```bash
ollama list
```

You need **`qwen2.5:1.5b`** in that list. If it is missing:

```bash
ollama pull qwen2.5:1.5b
```

> Ignore `qwen3.6:latest` if you see it — at 23 GB it exceeds this machine's 13.8 GB of RAM and cannot run. `qwen2.5:1.5b` is the correct model here.

---

## 2. First-time setup

### Backend

```bash
cd backend
uv sync
```

That creates `.venv/` and installs everything from `uv.lock`. The `.env` file is already present with local-only defaults — no editing needed to get started.

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
- `Orchestrator: StubOrchestrator (Ollama unreachable...)` — Ollama isn't running. The portal still works and the approval loop still runs; you just get deterministic canned output instead of model output.

Verify: <http://localhost:8000/api/health> returns `{"status":"ok"}`
API docs: <http://localhost:8000/docs>

### Terminal 3 — Frontend

```bash
cd frontend
npm run dev
```

Open <http://localhost:3000>

**Login:** `bhavesh` / `admin123` (seeded automatically on first backend start)

---

## 4. Using it

1. **Submit a job** — give the agents a brief, e.g. *"draft an intro email to Ravi Menon about deal D-002"*.
2. **Wait.** ⚠️ On CPU-only inference a segment takes **30 seconds to 3 minutes**. This is expected, not a hang. The UI shows segment-level progress.
3. **Approvals queue.** The agents stop when they propose anything touching money, legal documents, or outbound communication. The item appears in the queue — middle pane lists it, right pane shows the full draft.
4. **Approve or reject.** Approving starts a fresh segment that continues the job. Rejecting ends it.
5. **Activity** shows the append-only audit trail of everything that happened.

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

# Wait for the worker, then see what needs approving
sleep 30
curl -s localhost:8000/api/approvals -H "Authorization: Bearer $TOKEN"

# Approve it
curl -s -X POST localhost:8000/api/approvals/1/approve -H "Authorization: Bearer $TOKEN"

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
```

That last command is the important one. It enforces the architectural rule that `core/` imports nothing from `data/`, `api/`, `worker/`, `mcp/`, or `agents/` — and no FastAPI, SQLAlchemy or pydantic. If it reports **BROKEN**, a layering violation has crept in; fix the import rather than editing the contract.

Frontend:

```bash
cd frontend
npm run build      # must pass with no type errors
```

---

## 7. Troubleshooting

| Symptom                                    | Cause                              | Fix                                                        |
| ------------------------------------------ | ---------------------------------- | ---------------------------------------------------------- |
| `uv` not recognised                        | Terminal opened before uv install  | Close the terminal completely and open a new one           |
| Log says `StubOrchestrator`                | Ollama not reachable               | Start `ollama serve`, restart the backend                  |
| Job sits in `pending` forever              | Worker thread died                 | Restart the backend; check its log for a traceback         |
| Job takes minutes                          | **Normal** — CPU-only inference    | Not a bug. See ARCHITECTURE.md §2                          |
| Frontend shows "cannot reach API"          | Backend not running on :8000       | Start terminal 2                                           |
| Approval returns 409                       | Already decided                    | Each approval can be decided once, by design               |
| Approval returns 403                       | Logged in as a non-admin           | Only admins decide approvals                               |
| `lint-imports` BROKEN                      | Layering violation                 | Remove the offending import; don't relax the contract      |
| Model output is nonsense / no gate raised  | 1.5B model on CPU is weak          | Known limitation — see the caveat below                    |

---

## 8. Known limitations (read before trusting it)

- **The model is small.** `qwen2.5:1.5b` will not produce a clean tool call every run. When it doesn't propose an action, the job simply completes without raising a gate. The deterministic protection lives in `gate_policy` — but in v1 agents only *propose* actions; nothing actually sends email or moves money yet.
- **Not production-hardened.** The JWT secret in `.env` is a development default. Change it before anyone else uses this.
- **Single machine, single user at a time.** SQLite plus a serialized worker. Concurrent agent runs need Postgres first.
- **Nothing leaves the machine** — that is deliberate. See ARCHITECTURE.md §12.

---

## 9. Where things live

```
Aura/
├── PRD.md              # what we're building and why, with open decisions
├── ARCHITECTURE.md     # the design — read §3 (segments) and §5 (layering) first
├── RUNNING.md          # this file
├── backend/            # FastAPI + hexagonal core + agents + MCP
├── frontend/           # Next.js three-pane portal
└── docs/superpowers/plans/   # the implementation plans, task by task
```
