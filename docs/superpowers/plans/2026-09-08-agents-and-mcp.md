# Yuki OS Portal — Agents & MCP Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `StubOrchestrator` with a real CrewAI crew running on local Ollama, calling tools exposed by an MCP server, with every tool call classified by the deterministic gate policy.

**Architecture:** Both new packages are outbound adapters. `mcp/` implements `core.ports.toolbox`; `agents/` implements `core.ports.orchestrator`. `core/` is not modified except to add one new port file. The swap is a single line in `api/main.py` — this is the payoff of the hexagonal boundary.

**Tech Stack:** CrewAI, crewai-tools[mcp], mcp (Python SDK), Ollama (`qwen2.5:1.5b`), pytest.

**Spec:** `ARCHITECTURE.md` §2 (hardware constraints), §3 (gate), §4 (agent roster), §5 (ports). Depends on Plan 1 being complete.

## Global Constraints

- **Local-only inference.** `ollama/qwen2.5:1.5b` at `http://localhost:11434`. No cloud LLM, no OpenAI key, ever.
- **CrewAI memory MUST be disabled** (`memory=False`). CrewAI's default memory backend reaches for OpenAI embeddings, which violates the zero-spend constraint and will fail without a key.
- The model is 1.5B on CPU. **Assume malformed tool-call JSON** — repair is a component, not error handling.
- Agent chain is capped at **three agents**. Do not add a fourth.
- `core/` gains only `core/ports/toolbox.py`. No other core file changes.
- One segment = one crew run. The crew never waits for a human; it returns a proposed action and stops.

---

### Task 1: Toolbox port and MCP tool classification

**Files:**
- Create: `backend/src/aura/core/ports/toolbox.py`, `backend/src/aura/mcp/__init__.py`, `backend/src/aura/mcp/guard.py`
- Test: `backend/tests/unit/test_mcp_guard.py`

**Interfaces:**
- Produces: `ToolSpec(name: str, description: str, schema: dict)`; `Toolbox` Protocol with `list_tools() -> list[ToolSpec]` and `call(name: str, arguments: dict) -> str`; `classify_tools(specs) -> dict[str, ActionCategory]`; `is_gated(tool_name) -> bool`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_mcp_guard.py
from aura.core.domain.enums import ActionCategory
from aura.core.ports.toolbox import ToolSpec
from aura.mcp.guard import classify_tools, is_gated


def test_known_tools_get_their_category():
    specs = [ToolSpec(name="get_deal_status", description="", schema={}),
             ToolSpec(name="send_email", description="", schema={})]
    mapping = classify_tools(specs)
    assert mapping["get_deal_status"] is ActionCategory.INTERNAL_READ
    assert mapping["send_email"] is ActionCategory.OUTBOUND


def test_unmapped_tool_is_gated():
    """A new MCP server cannot silently create an ungated path outward."""
    specs = [ToolSpec(name="wire_transfer_v2", description="", schema={})]
    assert classify_tools(specs)["wire_transfer_v2"] is ActionCategory.UNKNOWN
    assert is_gated("wire_transfer_v2") is True


def test_internal_read_is_not_gated():
    assert is_gated("get_deal_status") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/test_mcp_guard.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'aura.core.ports.toolbox'`

- [ ] **Step 3: Write `core/ports/toolbox.py`**

```python
# backend/src/aura/core/ports/toolbox.py
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class ToolSpec:
    name: str
    description: str
    schema: dict = field(default_factory=dict)


@runtime_checkable
class Toolbox(Protocol):
    def list_tools(self) -> list[ToolSpec]: ...
    def call(self, name: str, arguments: dict) -> str: ...
```

- [ ] **Step 4: Write `mcp/guard.py`**

```python
# backend/src/aura/mcp/guard.py
"""Classify MCP tools into gate categories. Default-deny."""
from aura.core.domain.enums import ActionCategory
from aura.core.policy.gate_policy import classify, requires_approval
from aura.core.ports.toolbox import ToolSpec


def classify_tools(specs: list[ToolSpec]) -> dict[str, ActionCategory]:
    return {spec.name: classify(spec.name) for spec in specs}


def is_gated(tool_name: str) -> bool:
    return requires_approval(classify(tool_name))
```

- [ ] **Step 5: Run tests and the import contract**

```bash
cd backend
uv run pytest tests/unit/test_mcp_guard.py -v
uv run lint-imports --config .importlinter
```

Expected: 3 passed; contract KEPT.

- [ ] **Step 6: Commit**

```bash
git add backend/src/aura/core/ports/toolbox.py backend/src/aura/mcp backend/tests/unit/test_mcp_guard.py
git commit -m "feat: add toolbox port and default-deny MCP tool classification"
```

---

### Task 2: First-party MCP server

**Files:**
- Create: `backend/src/aura/mcp/servers/__init__.py`, `backend/src/aura/mcp/servers/deals_server.py`
- Test: `backend/tests/integration/test_deals_server.py`

**Interfaces:**
- Produces: a stdio MCP server exposing `get_deal_status(deal_id: str) -> str`, `list_deals() -> str`, `add_internal_note(deal_id: str, note: str) -> str`, `send_email(to: str, subject: str, body: str) -> str`. Tool names MUST match keys in `gate_policy.TOOL_CATEGORIES`.

- [ ] **Step 1: Add dependencies**

```bash
cd backend
uv add crewai "crewai-tools[mcp]" mcp
```

- [ ] **Step 2: Write the failing test**

```python
# backend/tests/integration/test_deals_server.py
from aura.mcp.servers.deals_server import add_internal_note, get_deal_status, list_deals


def test_get_deal_status_returns_known_deal():
    assert "Sunrise" in get_deal_status("D-001")


def test_get_deal_status_handles_unknown_deal():
    assert "No deal" in get_deal_status("D-999")


def test_list_deals_returns_all():
    result = list_deals()
    assert "D-001" in result and "D-002" in result


def test_add_internal_note_confirms():
    assert "D-001" in add_internal_note("D-001", "spoke to founder")
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/integration/test_deals_server.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 4: Write the server**

```python
# backend/src/aura/mcp/servers/deals_server.py
"""First-party MCP server. Run standalone over stdio, or import the plain functions.

Tool names must match keys in aura.core.policy.gate_policy.TOOL_CATEGORIES —
an unmapped name is treated as gated by default-deny.
"""
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("yuki-deals")

_DEALS = {
    "D-001": {"name": "Sunrise Infra", "stage": "NDA signed, awaiting mandate",
              "owner": "bhavesh"},
    "D-002": {"name": "Ravi Menon Ventures", "stage": "Sourced, no contact yet",
              "owner": "bhavesh"},
    "D-003": {"name": "Kaveri Textiles", "stage": "Closed - won", "owner": "bhavesh"},
}


@mcp.tool()
def get_deal_status(deal_id: str) -> str:
    """Look up the current stage of a deal by its ID (e.g. D-001)."""
    deal = _DEALS.get(deal_id)
    if deal is None:
        return f"No deal found with ID {deal_id}"
    return f"{deal_id} ({deal['name']}): {deal['stage']}, owned by {deal['owner']}"


@mcp.tool()
def list_deals() -> str:
    """List all deals with their current stage."""
    return "\n".join(f"{k} — {v['name']}: {v['stage']}" for k, v in _DEALS.items())


@mcp.tool()
def add_internal_note(deal_id: str, note: str) -> str:
    """Attach an internal note to a deal. Not visible outside the company."""
    return f"Note added to {deal_id}: {note}"


@mcp.tool()
def send_email(to: str, subject: str, body: str) -> str:
    """Send an outbound email. GATED — requires human approval before it is sent."""
    return f"Email queued to {to} with subject '{subject}'"


if __name__ == "__main__":
    mcp.run(transport="stdio")
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/integration/test_deals_server.py -v`
Expected: 4 passed

- [ ] **Step 6: Commit**

```bash
git add backend/src/aura/mcp/servers backend/tests/integration/test_deals_server.py backend/pyproject.toml backend/uv.lock
git commit -m "feat: add first-party deals MCP server"
```

---

### Task 3: Tool-call repair for a small model

**Files:**
- Create: `backend/src/aura/agents/__init__.py`, `backend/src/aura/agents/llm/__init__.py`, `backend/src/aura/agents/llm/repair.py`
- Test: `backend/tests/unit/test_repair.py`

**Interfaces:**
- Produces: `extract_json(text: str) -> dict | None` — recovers a JSON object from the messy output a 1.5B model produces (fenced code blocks, prose preamble, trailing commas, single quotes).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_repair.py
from aura.agents.llm.repair import extract_json


def test_plain_json():
    assert extract_json('{"tool": "send_email"}') == {"tool": "send_email"}


def test_json_in_fenced_code_block():
    text = 'Here is the call:\n```json\n{"tool": "send_email", "to": "a@b.com"}\n```\nDone.'
    assert extract_json(text) == {"tool": "send_email", "to": "a@b.com"}


def test_json_with_prose_preamble():
    assert extract_json('I will call {"tool": "list_deals"} now') == {"tool": "list_deals"}


def test_trailing_comma_is_repaired():
    assert extract_json('{"tool": "list_deals",}') == {"tool": "list_deals"}


def test_single_quotes_are_repaired():
    assert extract_json("{'tool': 'list_deals'}") == {"tool": "list_deals"}


def test_unrecoverable_returns_none():
    assert extract_json("I am not sure what to do here.") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_repair.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

```python
# backend/src/aura/agents/llm/repair.py
"""Recover structured output from a small local model.

A 1.5B model on CPU emits malformed tool-call JSON routinely. Per
ARCHITECTURE.md §2 rule 3, repair is a first-class component.
"""
import json
import re

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def _try_load(candidate: str) -> dict | None:
    try:
        value = json.loads(candidate)
    except (json.JSONDecodeError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def _repair(candidate: str) -> str:
    candidate = re.sub(r",\s*([}\]])", r"\1", candidate)  # trailing commas
    if '"' not in candidate and "'" in candidate:
        candidate = candidate.replace("'", '"')  # single-quoted keys/values
    return candidate


def _balanced_objects(text: str) -> list[str]:
    """Yield every balanced {...} span, outermost first."""
    spans, depth, start = [], 0, None
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth:
            depth -= 1
            if depth == 0 and start is not None:
                spans.append(text[start:i + 1])
    return spans


def extract_json(text: str) -> dict | None:
    """Best-effort extraction of a JSON object from model output."""
    if not text:
        return None

    candidates: list[str] = []
    candidates.extend(m.strip() for m in _FENCE.findall(text))
    candidates.append(text.strip())
    candidates.extend(_balanced_objects(text))

    for candidate in candidates:
        parsed = _try_load(candidate) or _try_load(_repair(candidate))
        if parsed is not None:
            return parsed
    return None
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_repair.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add backend/src/aura/agents backend/tests/unit/test_repair.py
git commit -m "feat: add tool-call JSON repair for small local model output"
```

---

### Task 4: Verify Ollama is reachable and the model answers

A **spike step** — confirm the environment before building on it.

**Files:**
- Create: `backend/src/aura/agents/llm/ollama_check.py`
- Test: `backend/tests/integration/test_ollama.py`

**Interfaces:**
- Produces: `ollama_available(base_url: str) -> bool`; `list_models(base_url: str) -> list[str]`

- [ ] **Step 1: Write the test (skips cleanly when Ollama is down)**

```python
# backend/tests/integration/test_ollama.py
import pytest

from aura.config import get_settings
from aura.agents.llm.ollama_check import list_models, ollama_available


def test_ollama_is_running_with_the_expected_model():
    base = get_settings().ollama_base_url
    if not ollama_available(base):
        pytest.skip("Ollama is not running — start it with `ollama serve`")
    assert any("qwen2.5:1.5b" in m for m in list_models(base)), \
        "Run: ollama pull qwen2.5:1.5b"
```

- [ ] **Step 2: Write the implementation**

```python
# backend/src/aura/agents/llm/ollama_check.py
import json
import urllib.error
import urllib.request


def ollama_available(base_url: str, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(f"{base_url}/api/tags", timeout=timeout):
            return True
    except (urllib.error.URLError, OSError):
        return False


def list_models(base_url: str, timeout: float = 5.0) -> list[str]:
    with urllib.request.urlopen(f"{base_url}/api/tags", timeout=timeout) as response:
        payload = json.load(response)
    return [m.get("name", "") for m in payload.get("models", [])]
```

- [ ] **Step 3: Run the test**

```bash
ollama list          # confirm qwen2.5:1.5b is present
uv run pytest tests/integration/test_ollama.py -v
```

Expected: PASS (or SKIP with a clear message if Ollama is not running).

- [ ] **Step 4: Commit**

```bash
git add backend/src/aura/agents/llm/ollama_check.py backend/tests/integration/test_ollama.py
git commit -m "test: verify local Ollama availability and model presence"
```

---

### Task 5: CrewAI orchestrator behind the port

**Files:**
- Create: `backend/src/aura/agents/crewai/__init__.py`, `backend/src/aura/agents/crewai/crews.py`, `backend/src/aura/agents/crewai/orchestrator.py`
- Test: `backend/tests/unit/test_crew_orchestrator.py`

**Interfaces:**
- Consumes: `Orchestrator`, `OrchestratorResult` (Plan 1 Task 5); `extract_json` (Task 3)
- Produces: `build_crew(llm, tools) -> Crew` (Researcher → Drafter → Reviewer, `memory=False`); `CrewOrchestrator(llm=None, tools=None)` implementing `Orchestrator`; `decide_action(crew_output: str, context_in: dict) -> ProposedAction | None`

- [ ] **Step 1: Write the failing test — the pure decision logic, no LLM required**

```python
# backend/tests/unit/test_crew_orchestrator.py
from aura.core.domain.enums import ActionCategory
from aura.core.ports.orchestrator import Orchestrator
from aura.agents.crewai.orchestrator import CrewOrchestrator, decide_action


def test_crew_orchestrator_satisfies_the_port():
    assert isinstance(CrewOrchestrator(), Orchestrator)


def test_decide_action_extracts_a_gated_tool_call():
    output = 'I will send this. ```json{"tool": "send_email", "arguments": {"to": "a@b.com"}}```'
    action = decide_action(output, {"brief": "intro"})
    assert action is not None
    assert action.tool == "send_email"
    assert action.category is ActionCategory.OUTBOUND


def test_decide_action_returns_none_for_ungated_tool():
    output = '{"tool": "get_deal_status", "arguments": {"deal_id": "D-001"}}'
    assert decide_action(output, {}) is None


def test_unmapped_tool_is_treated_as_gated():
    output = '{"tool": "wire_transfer", "arguments": {}}'
    action = decide_action(output, {})
    assert action is not None
    assert action.category is ActionCategory.UNKNOWN


def test_no_tool_call_means_no_action():
    assert decide_action("Here is a draft with no tool call.", {}) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_crew_orchestrator.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write `crews.py`**

```python
# backend/src/aura/agents/crewai/crews.py
"""The v1 roster from ARCHITECTURE.md §4: Researcher -> Drafter -> Reviewer.

Three agents is a hard ceiling on CPU-only inference. Do not add a fourth.
"""
from crewai import Agent, Crew, Process, Task


def build_crew(llm, tools: list | None = None) -> Crew:
    tools = tools or []

    researcher = Agent(
        role="Deal Researcher",
        goal="Gather the facts needed about a deal. Never invent data.",
        backstory="You look up real records before answering. If a tool can "
                  "answer, you call it. You answer in two sentences.",
        tools=tools, llm=llm, allow_delegation=False, verbose=False,
    )
    drafter = Agent(
        role="Drafter",
        goal="Write the requested business artifact using only the researcher's facts.",
        backstory="You write concise, professional Indian business correspondence. "
                  "You never send anything yourself — you produce a draft.",
        tools=tools, llm=llm, allow_delegation=False, verbose=False,
    )
    reviewer = Agent(
        role="Reviewer",
        goal="Check the draft for factual errors and unprofessional tone.",
        backstory="You are terse. You reply either 'APPROVED' plus the final "
                  "draft, or list the specific problems.",
        tools=[], llm=llm, allow_delegation=False, verbose=False,
    )

    research_task = Task(
        description="Gather the facts needed for this brief: {brief}",
        expected_output="Two sentences of factual context.", agent=researcher,
    )
    draft_task = Task(
        description="Write the artifact requested by this brief: {brief}",
        expected_output="The finished draft text.", agent=drafter,
        context=[research_task],
    )
    review_task = Task(
        description="Review the draft. If it should be sent, state the tool call "
                    'as JSON: {{"tool": "send_email", "arguments": {{...}}}}',
        expected_output="Either APPROVED plus the draft, or a list of problems.",
        agent=reviewer, context=[draft_task],
    )

    # memory=False is REQUIRED — CrewAI's memory backend reaches for OpenAI
    # embeddings, which violates the local-only, zero-spend constraint.
    return Crew(agents=[researcher, drafter, reviewer],
                tasks=[research_task, draft_task, review_task],
                process=Process.sequential, memory=False, verbose=False)
```

- [ ] **Step 4: Write `orchestrator.py`**

```python
# backend/src/aura/agents/crewai/orchestrator.py
"""CrewAI adapter for core.ports.orchestrator.

One segment = one crew run. The crew never waits for a human: it either
finishes the job or returns a proposed action and stops.
"""
from aura.agents.llm.repair import extract_json
from aura.core.domain.segment import ProposedAction
from aura.core.policy.gate_policy import classify, requires_approval
from aura.core.ports.orchestrator import OrchestratorResult


def decide_action(crew_output: str, context_in: dict) -> ProposedAction | None:
    """Parse the crew's output for a tool call that needs approval."""
    parsed = extract_json(crew_output)
    if not parsed or "tool" not in parsed:
        return None

    tool = str(parsed["tool"])
    category = classify(tool)
    if not requires_approval(category):
        return None

    arguments = parsed.get("arguments") or {}
    summary = str(context_in.get("brief") or f"Run {tool}")
    return ProposedAction(tool=tool, category=category,
                          arguments=arguments if isinstance(arguments, dict) else {},
                          summary=summary)


class CrewOrchestrator:
    """Implements core.ports.orchestrator.Orchestrator."""

    def __init__(self, llm=None, tools: list | None = None):
        self._llm = llm
        self._tools = tools or []

    def _make_llm(self):
        if self._llm is not None:
            return self._llm
        from crewai import LLM

        from aura.config import get_settings
        s = get_settings()
        return LLM(model=f"ollama/{s.ollama_model}", base_url=s.ollama_base_url)

    def run(self, context_in: dict) -> OrchestratorResult:
        # A segment resumed after approval carries an approved draft: finish.
        if context_in.get("approved_draft") or context_in.get("sent"):
            return OrchestratorResult(completed=True,
                                      context_out={**context_in, "sent": True},
                                      proposed_action=None)

        from aura.agents.crewai.crews import build_crew

        crew = build_crew(self._make_llm(), self._tools)
        output = str(crew.kickoff(inputs={"brief": context_in.get("brief", "")}))

        action = decide_action(output, context_in)
        if action is not None:
            return OrchestratorResult(
                completed=False,
                context_out={**context_in, "draft": output, "approved_draft": True},
                proposed_action=action,
            )
        return OrchestratorResult(completed=True,
                                  context_out={**context_in, "draft": output},
                                  proposed_action=None)
```

- [ ] **Step 5: Run tests and the import contract**

```bash
uv run pytest tests/unit -v
uv run lint-imports --config .importlinter
```

Expected: all pass; contract KEPT (core still imports no CrewAI).

- [ ] **Step 6: Commit**

```bash
git add backend/src/aura/agents/crewai backend/tests/unit/test_crew_orchestrator.py
git commit -m "feat: add CrewAI orchestrator adapter with three-agent crew"
```

---

### Task 6: Wire the real orchestrator in, with a safe fallback

**Files:**
- Modify: `backend/src/aura/api/main.py` (the `on_startup` function from Plan 1 Task 12 Step 5)
- Create: `backend/src/aura/agents/factory.py`
- Test: `backend/tests/unit/test_orchestrator_factory.py`

**Interfaces:**
- Produces: `make_orchestrator() -> Orchestrator` — returns `CrewOrchestrator` when Ollama is reachable, otherwise `StubOrchestrator`, logging which was chosen.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_orchestrator_factory.py
from aura.agents.factory import make_orchestrator
from aura.core.ports.orchestrator import Orchestrator


def test_factory_returns_something_satisfying_the_port():
    assert isinstance(make_orchestrator(), Orchestrator)


def test_factory_falls_back_to_stub_when_ollama_is_down():
    orchestrator = make_orchestrator(base_url="http://localhost:1")
    assert type(orchestrator).__name__ == "StubOrchestrator"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_orchestrator_factory.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'aura.agents.factory'`

- [ ] **Step 3: Write the factory**

```python
# backend/src/aura/agents/factory.py
import logging

from aura.agents.llm.ollama_check import ollama_available
from aura.config import get_settings
from aura.core.ports.orchestrator import Orchestrator

logger = logging.getLogger(__name__)


def make_orchestrator(base_url: str | None = None) -> Orchestrator:
    """Real crew when Ollama is up; deterministic stub otherwise.

    The portal stays usable with no model running — the approval loop is
    exercised either way.
    """
    url = base_url or get_settings().ollama_base_url

    if ollama_available(url):
        try:
            from aura.agents.crewai.orchestrator import CrewOrchestrator
            logger.info("Orchestrator: CrewAI on %s", url)
            return CrewOrchestrator()
        except Exception as exc:
            logger.warning("CrewAI unavailable (%s) — falling back to stub", exc)

    from aura.worker.stub_orchestrator import StubOrchestrator
    logger.warning("Orchestrator: StubOrchestrator (Ollama unreachable at %s)", url)
    return StubOrchestrator()
```

- [ ] **Step 4: Swap the orchestrator in `api/main.py`**

Replace the line `app.state.worker_stop = start_worker(StubOrchestrator(), hub)` with:

```python
    app.state.worker_stop = start_worker(make_orchestrator(), hub)
```

Replace the import `from aura.worker.stub_orchestrator import StubOrchestrator` with:

```python
from aura.agents.factory import make_orchestrator
```

- [ ] **Step 5: Run the whole suite**

```bash
uv run pytest tests -v
uv run lint-imports --config .importlinter
```

Expected: all pass; contract KEPT.

- [ ] **Step 6: End-to-end with the real model**

```bash
ollama serve            # in its own terminal, if not already running
uv run uvicorn aura.api.main:app --port 8000
```

The log must read `Orchestrator: CrewAI on http://localhost:11434`. Then:

```bash
TOKEN=$(curl -s -X POST localhost:8000/api/auth/login -H 'Content-Type: application/json' \
  -d '{"username":"bhavesh","password":"admin123"}' | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

curl -s -X POST localhost:8000/api/jobs -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"inputs":{"brief":"draft an intro email to Ravi Menon about deal D-002"}}'
```

Expected: the segment takes **30 s – 3 min** on CPU (this is normal per ARCHITECTURE.md §2). Then `GET /api/approvals` shows a pending approval whose `proposed_action.summary` reflects the brief. Approving it drives the job to `complete`.

- [ ] **Step 7: Commit**

```bash
git add backend/src/aura/agents/factory.py backend/src/aura/api/main.py backend/tests/unit/test_orchestrator_factory.py
git commit -m "feat: run real CrewAI orchestrator with stub fallback when Ollama is down"
```

---

## Self-Review

**Spec coverage:**

| ARCHITECTURE.md requirement                   | Covered by                          |
| --------------------------------------------- | ----------------------------------- |
| §2 rule 3 — assume malformed output          | Task 3 (`repair.py`)                |
| §3 default-deny on MCP tools                  | Task 1 (`guard.py`)                 |
| §4 three-agent roster, no fourth              | Task 5 (`crews.py`)                 |
| §5 CrewAI behind `orchestrator` port          | Task 5, verified by `isinstance` test |
| §10 local-only, zero API spend                | Task 5 (`memory=False`), Task 4     |
| §11 "CrewAI awkward to drive" mitigation      | Task 6 (fallback keeps portal usable) |

**Type consistency:** `OrchestratorResult(completed, context_out, proposed_action)` and `ProposedAction(tool, category, arguments, summary)` match Plan 1 Tasks 2 and 5 exactly. `StubOrchestrator` is imported from `aura.worker.stub_orchestrator`, where Plan 1 Task 12 creates it.

**Known limitation, stated honestly:** `qwen2.5:1.5b` will not reliably emit a clean tool call every run. `decide_action` returning `None` means the job completes without a gate rather than failing — acceptable for v1, but it means **gate coverage depends on the model cooperating**. The deterministic guarantee lives in `gate_policy`, which is what actually protects real outbound actions once tools are executed rather than merely proposed. Executing approved actions for real is deliberately out of scope for this plan.
