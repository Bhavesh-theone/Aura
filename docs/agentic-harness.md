# Aura — Agentic Harness Architecture

**Date:** 2026-10-07 · **Diagram:** [architecture/agentic-harness.html](architecture/agentic-harness.html). It is an interactive standalone page with light/dark themes, guided views and export; the source is [architecture/agentic-harness.workflow.json](architecture/agentic-harness.workflow.json).

An **agentic harness** is everything around the model that turns it into a reliable agent: trigger, context, loop, model access, tools, policy, human approval, state, telemetry, evaluation, isolation, recovery and delivery. This document does three things:
1. Defines the standard harness categories, from industry sources.
2. Maps every micro-step of Aura's agent loop to those categories, with code references.
3. Scores Aura's coverage and lists the gaps.

Paths are relative to `backend/src/aura/` unless noted.

![Aura agentic harness](architecture/agentic-harness.visual-check.1440x900.light.png)

---

## 1. The 13 harness categories

Synthesised from Anthropic's [Building effective agents](https://www.anthropic.com/research/building-effective-agents) and [context engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) posts, LangGraph's [human-in-the-loop](https://docs.langchain.com/oss/python/langgraph/human-in-the-loop) and [persistence](https://docs.langchain.com/oss/python/langgraph/persistence) docs, [CrewAI tasks](https://docs.crewai.com/en/concepts/tasks), the MCP primitives, [NeMo Guardrails](https://docs.nvidia.com/nemo/guardrails/0.19.0/user-guides/guardrails-process.html), [OpenTelemetry GenAI agent spans](https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-agent-spans), and 12-factor agents. These came from search summaries; read the primary pages before relying on fine detail.

| # | Category | What it covers |
|---|---|---|
| 1 | Trigger / Ingress | Starting a run: authenticate, authorise, normalise, deduplicate, assign a run ID |
| 2 | Context assembly | Building what the model sees: template, state, retrieval, tool specs, compaction |
| 3 | Planning / Orchestration | Control flow: single loop, workflow pattern or multi-agent; termination |
| 4 | Model access | Calling the model reliably: routing, retries, failover, structured output and repair, tokens and cost |
| 5 | Tools & actions | Tool schemas, argument validation, execution, MCP, result normalisation |
| 6 | Policy & guardrails | Input and output checks, authorisation before a tool runs, materiality, permissions |
| 7 | Human-in-the-loop | Interrupt, checkpoint, notify, decide, resume |
| 8 | State & memory | Run state, checkpoints, durable records, long-term memory |
| 9 | Observability & lineage | Traces and spans, prompt and version logging, tokens, cost, latency |
| 10 | Evaluation & feedback | Golden sets, offline and online evals, override rates, promotion and demotion |
| 11 | Security & isolation | Data scoping, least privilege, secrets, sandboxing, prompt-injection defence |
| 12 | Error handling & recovery | Retries, fallbacks, dead letters, idempotency, resume after a crash |
| 13 | Delivery / Egress | Results, events, notifications, audit log |

---

## 2. Aura's micro-steps by category

Legend: **[LLM]** = the model decides · **[Code]** = deterministic code decides.

### 1. Trigger / Ingress
1. `POST /api/jobs` returns 202. The request runs in one unit of work, with every repository built for the requesting user (`api/routers/jobs.py:18-28`, `api/deps.py:31-44, 84-146`).
2. **[Code]** Role check: only dealmaker and analyst may submit (`core/services/submit_job.py:68`, `core/policy/rbac_policy.py:26-32`).
3. **[Code]** Wall check: a deal the user can't see returns 404 (`submit_job.py:71-74`).
4. **[Code]** The capability must be `classify_document`, `draft_email` or `extract_financials`, otherwise 422 (`submit_job.py:16, 77-81`).
5. The job is written as PENDING and segment 1 as QUEUED; then come an audit row and a `job_submitted` event (`submit_job.py:83-94`).

### 2. Context assembly
6. **[Code]** Enrichment at submit time, as the user: the document's first 2,000 characters, or the party link (`submit_job.py:20-45`).
7. A `RunContext` is built with job, deal, acting username and the run-record sink (`core/services/run_segment.py:94-95`).
8. **[Code]** `acting_as(username)` makes the MCP tools read through the user's walls when they run (`mcp/identity.py:7-22`, `agents/crewai/orchestrator.py:144`).
9. Each role has its own prompt template (`agents/crewai/crews.py:9-19`).

### 3. Planning / Orchestration
10. **[Code]** The orchestrator is chosen once at startup: CrewAI if Ollama answers, otherwise the stub (`agents/factory.py:18-28`).
11. **[Code]** The worker thread polls every 2 seconds and runs the escalation sweep before each claim (`worker/runner.py:89-106`).
12. **[Code]** The segment and job are marked RUNNING and committed (`run_segment.py:87-92`).
13. **[Code]** Resume short-circuit: an already-approved context completes without a model call (`orchestrator.py:134-138`).
14. **[Code]** Dispatch by capability (`orchestrator.py:145-151`).
    - Classify and extract use one agent with no tools (`crews.py:22-63`).
    - Draft email uses a sequential Researcher → Drafter → Reviewer crew, with memory off (`crews.py:66-111`).

### 4. Model access
15. `crewai.LLM("ollama/qwen3.5:4b")`; the model version is the Ollama digest (`orchestrator.py:116-130`).
16. Every `call()` goes through a recording wrapper (`agents/crewai/recording_llm.py:20-43`).
17. **[LLM]** Document class, extracted figures, draft and review text, and confidence.
18. **[Code]** JSON repair: fenced blocks, balanced braces, trailing commas, quotes (`agents/llm/repair.py:42-56`).
19. **[Code]** Parse fallbacks: keep the current class, or null figures, at confidence 0.0 (`orchestrator.py:48-58, 90-100`).

### 5. Tools & actions
20. Four deals-MCP functions are wrapped as `GatedTool`s, with argument schemas taken from the function signatures (`agents/crewai/tools.py:73-92`).
21. **[LLM]** Which tools the agent tries to call.
22. **[Code]** Ungated tools (internal read/write) run as the acting user (`tools.py:55-60`).

### 6. Policy & guardrails
23. **[Code]** Gate classification: anything not internal read/write is gated, and so is anything unmapped or above the ₹5 Cr materiality cap (`core/policy/gate_policy.py:30-45`).
24. **[Code]** Gated tool bodies **never execute**; the agent receives a blocked message (`tools.py:41-46`).
25. **[Code]** Approval is re-checked on the proposed action (`run_segment.py:116-117`).
26. **[Code]** Trigger precedence: materiality gate, then confidence below 0.95, then policy required (`run_segment.py:26-33`).
27. **[Code]** Policy builds the handoff package and picks the recommendation, not the model (`core/policy/handoff_policy.py:132-172`, `gate_policy.py:48-54`).
28. **[Code]** Schema validation (`handoff_policy.py:41-97`).
    - A bot-to-human handoff needs `decision_required` (question, 2–5 options, a recommendation among them, confidence), plus `if_you_do_nothing`, `what_happened` and `evidence`.
    - A directive needs reasoning of at least 30 characters, `do_not_revisit`, and `next_checkpoint`.

### 7. Human-in-the-loop
29. The segment and job become AWAITING_APPROVAL.
30. **[Code]** `do_not_revisit` skip path: if an earlier directive on this deal covers the task type, the earlier decision is applied and audited (`run_segment.py:36-46, 118-129`).
31. Otherwise a task (REVIEW) and handoff (OPEN, `auto_escalate_at` +24h) are created, with an audit row and event (`core/services/handoffs.py:24-83`).
32. The Decisions inbox lists open and escalated handoffs, filtered by wall (`api/routers/handoffs.py:25-30`).
33. **[Code]** Resolve runs these checks in order (`handoffs.py:141-204`):
    - role check;
    - 404 if not found;
    - 409 if already resolved;
    - compliance allowed only for `policy_required`;
    - directive validation (a 422 is audited as `handoff_rejected`).
34. **[Code]** Approve, confirm or verify queues segment n+1; anything else rejects the job (`handoffs.py:104-123`).
35. **[Code]** The escalation sweep marks overdue handoffs ESCALATED (`handoffs.py:207-221`).

### 8. State & memory
36. Tables: `jobs`, `segments` (unique on job + seq), `task`, `handoff`, `agent_run`, and the append-only `audit_entries` (`data/models/tables.py`, `data/triggers.py`).
37. Transactions: one per API request; two per worker segment, plus an immediate `agent_run` commit (`data/uow.py:14-63`).
38. There is no long-term agent memory (the crew runs with `memory=False`); continuity comes from the job and segment `context_out` → `context_in`.

### 9. Observability & lineage
39. **[Code]** Each run is written with `prompt_hash` (SHA-256 of the canonical messages), `input_digest`, output, tokens, latency and `cost_inr=0`. If the record can't be written, the output is **not used** (`agents/llm/recording.py:44-97`, `core/policy/lineage_policy.py:7-13`).
40. Run records commit immediately, so they survive a segment rollback (`data/run_sink.py:21-28`).
41. Hash-chained audit with an anchor file, written under a thread lock (`data/repositories/sql.py:226-239`, `core/domain/audit.py:22-32`).
42. Metrics: `runs_traceable_pct`, `audit_chain_ok`, `handoff_rejections_422`, `outbound_executed` (`api/routers/metrics.py:16-35`).

### 10. Evaluation & feedback
43. There are no golden datasets, no offline evals and no override-rate tracking. The 0.95 confidence threshold is the only quality gate.

### 11. Security & isolation
44. **[Code]** Deal walls bind every repository, including MCP tool reads during agent runs. Off-wall data returns 404.
45. Everything runs locally (Ollama), with telemetry disabled. No data leaves the machine.
46. The worker uses SYSTEM-scoped repositories. User scoping is applied at submit time and through `acting_as` for tools.

### 12. Error handling & recovery
47. Any exception rolls back, marks the segment and job FAILED, and writes a `segment_failed` audit row and event (`run_segment.py:151-164`).
48. A failure to write the run record raises `AgentRunLogError`, which fails the segment. Parse failures lower confidence instead.
49. Errors outside the segment's try block roll back and are logged (`runner.py:60-62, 97-98`).

### 13. Delivery / Egress
50. Every audited mutation emits `entity_changed {kind, deal_id}` after commit (`core/services/notifying_audit.py:13-18`).
51. The WebSocket at `/ws/events` (JWT) delivers deal events **only to members of that deal's wall** and drops them if the wall can't be read (`api/ws/hub.py:47-72`).
52. The frontend keeps one socket with backoff, refetches on matching events, and polls every 20 seconds when the socket is down (`frontend/shared/api/ws.ts`, `events.tsx`).
53. Nothing is ever sent outbound: `outbound_executed` is never written (`core/services/outbound.py`).

---

## 3. Who decides what

| The model decides | Code decides |
|---|---|
| Proposed document class, its confidence and rationale | Role and permission checks, wall scoping |
| Extracted figures and confidence | Allowed capabilities, context enrichment |
| Research, draft and review text | Orchestrator choice, dispatch, resume short-circuit |
| Which tools the agent tries to call | Gate category, materiality cap, 0.95 confidence gate |
| | Handoff options **and recommendation**, schema validation |
| | `do_not_revisit` skip, continue or reject, escalation |
| | Parse fallbacks, run-record lineage, audit |

This follows the 12-factor principle: the model proposes, and deterministic code owns control flow and every consequential decision.

---

## 4. Coverage scorecard

| # | Category | Aura | Notes |
|---|---|---|---|
| 1 | Trigger / Ingress | ✅ Strong | Role, wall and capability checks. **Gap:** no idempotency key on `POST /api/jobs` |
| 2 | Context assembly | 🟡 Partial | Per-role templates, user-scoped enrichment. **Gap:** no retrieval or RAG, no compaction; context is frozen at submit time |
| 3 | Orchestration | 🟡 Partial | Capability dispatch, sequential crew, resume short-circuit. **Gap:** no explicit turn or budget limit |
| 4 | Model access | 🟡 Partial | Recording wrapper, JSON repair, safe fallbacks. **Gaps:** no retries or failover; the stub is chosen only at startup |
| 5 | Tools & actions | ✅ Strong | Gated MCP wrappers; gated bodies never run. **Gaps:** the standalone stdio MCP server doesn't gate `send_email` itself; `add_internal_note` writes nothing |
| 6 | Policy & guardrails | ✅ Strong | Deterministic gate, materiality, confidence, policy-chosen recommendation, schema validation |
| 7 | Human-in-the-loop | ✅ Strong | Structured handoffs, directives, `do_not_revisit`, escalation. **Gap:** a resolve race (read-then-check, no row lock) |
| 8 | State & memory | 🟡 Partial | Durable job, segment, task and handoff records. **Gaps:** no atomic segment claim; a crash leaves segments stuck RUNNING; no long-term memory |
| 9 | Observability & lineage | ✅ Strong | Run records written before use, hash-chained audit, metrics. **Gaps:** no OpenTelemetry spans; `agent_run.task_id` is never set; resume segments write no run rows |
| 10 | Evaluation & feedback | ❌ Missing | No golden sets, offline evals, override-rate tracking or autonomy demotion (SOSPE §9.6) |
| 11 | Security & isolation | ✅ Strong | Walls also bind agent tools; local-only. **Gaps:** no prompt-injection screening of document text; the worker runs with SYSTEM scope |
| 12 | Error handling & recovery | 🟡 Partial | Rollback plus `segment_failed`. **Gaps:** no retries, dead letter or stuck-run recovery; a `HandoffRejected` raised in the worker is recorded as `segment_failed` |
| 13 | Delivery / Egress | ✅ Strong | Wall-filtered WebSocket, audited events, nothing sent outbound |

**Totals:** 7 strong · 5 partial · 1 missing.

---

## 5. Recommended fixes, by risk

| Priority | Fix | Category |
|---|---|---|
| 1 | Atomic segment claim (`UPDATE … WHERE status='queued'` returning the row), plus recovery of stale RUNNING segments at startup | 8, 12 |
| 2 | Row lock or conditional update on handoff resolve, so two resolves can't both pass | 7 |
| 3 | Gate inside the standalone deals MCP server too, not only in the CrewAI wrapper | 5, 6 |
| 4 | Evaluation loop: golden sets for classify and extract, override-rate tracking from directives, automatic demotion | 10 |
| 5 | Per-call retry and fallback to the stub when Ollama fails mid-run; idempotency key on job submit | 4, 1 |
| 6 | Prompt-injection screening of document text before it enters context | 11 |
| 7 | OpenTelemetry GenAI spans around each segment, model call and tool call, linked to `agent_run` and the audit trail | 9 |

---

## 6. Code notes from the trace

These are small inconsistencies found while tracing, worth tidying:
- **Ignored result flag.** `run_segment` never reads `OrchestratorResult.completed`, so a confident extraction completes the job with no handoff (by design, but implicit).
- **Misleading marker.** The crew's brief path sets `approved_draft: True` before any approval. It is really the resume marker (`orchestrator.py:175`).
- **Dropped tool attempts.** Gated tool attempts made during the draft-email crew are discarded (`orchestrator.py:226`).
- **Skip-path events.** The skip path emits no `handoff_created` event, only `entity_changed`. Its directive match covers any resolved directive on the deal, rejections included.
