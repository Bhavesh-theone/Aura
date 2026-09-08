# Yuki OS Portal — Backend Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a runnable FastAPI backend where a user can submit a job, have it run as durable segments, stop at a human approval gate, and resume on approval — with every action audited.

**Architecture:** Hexagonal. A framework-free `core/` package holds domain entities, deterministic policy, ports (interfaces) and use cases. Adapters (`data/`, `api/`, `worker/`) depend inward on core; core imports nothing from them. This plan uses a **stub orchestrator** satisfying `core.ports.orchestrator`, so the whole approval loop is testable with no LLM. Plan 2 swaps in CrewAI behind that same port without touching core.

**Tech Stack:** Python 3.13, uv, FastAPI, SQLAlchemy 2.x, Alembic, SQLite, pydantic-settings, python-jose (JWT), passlib[bcrypt], pytest, import-linter.

**Spec:** `ARCHITECTURE.md` (§3 segmented execution, §5 dependency rule, §6 backend structure, §8 data model) and `PRD.md`.

## Global Constraints

- Python **3.13**; all Python commands run through **uv** (`uv run`, `uv add`).
- Package root is `backend/src/aura/`; installed as package `aura`.
- **`core/` imports nothing from `data/`, `api/`, `worker/`, `mcp/`, `agents/`** — and no `fastapi`, `sqlalchemy`, or `pydantic`. Enforced by `.importlinter`.
- Domain objects are **plain dataclasses**. Pydantic lives only in `api/schemas/` and `config.py`.
- Gate classification is **default-deny**: an action whose category is unknown is treated as gated.
- `AuditEntry` is **append-only** — repositories expose no update or delete.
- All timestamps are timezone-aware UTC (`datetime.now(timezone.utc)`).
- Commit after every task. Conventional commit prefixes (`feat:`, `test:`, `chore:`).

---

### Task 1: Project scaffold, git, and the enforced dependency rule

**Files:**
- Create: `.gitignore`, `backend/pyproject.toml`, `backend/.importlinter`, `backend/src/aura/__init__.py`, `backend/src/aura/core/__init__.py`, `backend/tests/unit/test_smoke.py`

**Interfaces:**
- Consumes: nothing
- Produces: a `uv`-managed package `aura` importable in tests; `uv run pytest` and `uv run lint-imports` both green.

- [ ] **Step 1: Initialise git at the repo root**

```bash
cd /c/Users/Bhavesh/Desktop/Aura
git init
```

- [ ] **Step 2: Write `.gitignore` at repo root**

```gitignore
__pycache__/
*.py[cod]
.venv/
.env
*.db
*.sqlite3
node_modules/
.next/
.superpowers/
.pytest_cache/
```

- [ ] **Step 3: Create the uv project**

```bash
cd backend
uv init --no-readme --python 3.13 .
uv add fastapi "uvicorn[standard]" sqlalchemy alembic "python-jose[cryptography]" "passlib[bcrypt]" python-multipart pydantic-settings
uv add --dev pytest pytest-asyncio httpx import-linter
```

- [ ] **Step 4: Replace `backend/pyproject.toml` build config so `src/` layout works**

Add these sections to `backend/pyproject.toml` (keep the generated `[project]` and dependency lists):

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/aura"]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
```

- [ ] **Step 5: Create package directories**

```bash
mkdir -p src/aura/core/domain src/aura/core/policy src/aura/core/ports src/aura/core/services
mkdir -p src/aura/data/models src/aura/data/repositories src/aura/api/routers src/aura/api/schemas src/aura/api/ws src/aura/worker
mkdir -p tests/unit tests/integration
for d in src/aura src/aura/core src/aura/core/domain src/aura/core/policy src/aura/core/ports src/aura/core/services \
         src/aura/data src/aura/data/models src/aura/data/repositories \
         src/aura/api src/aura/api/routers src/aura/api/schemas src/aura/api/ws src/aura/worker; do
  touch "$d/__init__.py"
done
```

- [ ] **Step 6: Write `backend/.importlinter` — the dependency rule from ARCHITECTURE.md §5**

```ini
[importlinter]
root_package = aura

[importlinter:contract:core-is-pure]
name = Core depends on nothing internal
type = forbidden
source_modules =
    aura.core
forbidden_modules =
    aura.data
    aura.api
    aura.worker
    aura.mcp
    aura.agents
    fastapi
    sqlalchemy
    pydantic
```

- [ ] **Step 7: Write the smoke test**

```python
# backend/tests/unit/test_smoke.py
def test_package_imports():
    import aura

    assert aura is not None
```

- [ ] **Step 8: Run tests and the import contract**

```bash
uv run pytest tests/unit/test_smoke.py -v
uv run lint-imports --config .importlinter
```

Expected: 1 passed; import contract `core-is-pure` KEPT.

- [ ] **Step 9: Commit**

```bash
cd /c/Users/Bhavesh/Desktop/Aura
git add .gitignore backend/
git commit -m "chore: scaffold backend package with enforced hexagonal import contract"
```

---

### Task 2: Core domain entities

**Files:**
- Create: `backend/src/aura/core/domain/enums.py`, `job.py`, `segment.py`, `approval.py`, `user.py`, `audit.py`
- Test: `backend/tests/unit/test_domain.py`

**Interfaces:**
- Produces:
  - `ActionCategory` (`MONEY`, `LEGAL`, `OUTBOUND`, `INTERNAL_READ`, `INTERNAL_WRITE`, `UNKNOWN`)
  - `JobStatus` (`PENDING`, `RUNNING`, `AWAITING_APPROVAL`, `COMPLETE`, `FAILED`, `REJECTED`)
  - `SegmentStatus` (`QUEUED`, `RUNNING`, `AWAITING_APPROVAL`, `DONE`, `FAILED`)
  - `ApprovalStatus` (`PENDING`, `APPROVED`, `REJECTED`)
  - `Role` (`ADMIN`, `MEMBER`)
  - `ProposedAction(tool: str, category: ActionCategory, arguments: dict, summary: str)`
  - `Job(id: int | None, status: JobStatus, inputs: dict, deal_id: int | None, result: dict | None, created_at: datetime)`
  - `Segment(id, job_id, seq: int, status, context_in: dict, context_out: dict | None, started_at, ended_at)`
  - `Approval(id, segment_id, category, proposed_action: dict, status, decided_by: int | None, decided_at)`
  - `User(id, username, password_hash, role)`
  - `AuditEntry(id, job_id, actor: str, action: str, payload: dict, created_at)`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_domain.py
from datetime import datetime, timezone

from aura.core.domain.enums import ActionCategory, JobStatus, SegmentStatus
from aura.core.domain.job import Job
from aura.core.domain.segment import Segment, ProposedAction


def test_job_starts_pending():
    job = Job(id=None, status=JobStatus.PENDING, inputs={"brief": "draft intro"},
              deal_id=None, result=None, created_at=datetime.now(timezone.utc))
    assert job.status is JobStatus.PENDING


def test_segment_sequence_starts_at_one():
    seg = Segment(id=None, job_id=1, seq=1, status=SegmentStatus.QUEUED,
                  context_in={}, context_out=None, started_at=None, ended_at=None)
    assert seg.seq == 1
    assert seg.context_out is None


def test_proposed_action_carries_category():
    action = ProposedAction(tool="send_email", category=ActionCategory.OUTBOUND,
                            arguments={"to": "a@b.com"}, summary="Send intro email")
    assert action.category is ActionCategory.OUTBOUND
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_domain.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'aura.core.domain.enums'`

- [ ] **Step 3: Write `enums.py`**

```python
# backend/src/aura/core/domain/enums.py
from enum import Enum


class ActionCategory(str, Enum):
    MONEY = "money"
    LEGAL = "legal"
    OUTBOUND = "outbound"
    INTERNAL_READ = "internal_read"
    INTERNAL_WRITE = "internal_write"
    UNKNOWN = "unknown"


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETE = "complete"
    FAILED = "failed"
    REJECTED = "rejected"


class SegmentStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    DONE = "done"
    FAILED = "failed"


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class Role(str, Enum):
    ADMIN = "admin"
    MEMBER = "member"
```

- [ ] **Step 4: Write `job.py`, `segment.py`, `approval.py`, `user.py`, `audit.py`**

```python
# backend/src/aura/core/domain/job.py
from dataclasses import dataclass
from datetime import datetime

from aura.core.domain.enums import JobStatus


@dataclass
class Job:
    id: int | None
    status: JobStatus
    inputs: dict
    deal_id: int | None
    result: dict | None
    created_at: datetime
```

```python
# backend/src/aura/core/domain/segment.py
from dataclasses import dataclass, field
from datetime import datetime

from aura.core.domain.enums import ActionCategory, SegmentStatus


@dataclass
class ProposedAction:
    tool: str
    category: ActionCategory
    arguments: dict
    summary: str


@dataclass
class Segment:
    id: int | None
    job_id: int
    seq: int
    status: SegmentStatus
    context_in: dict = field(default_factory=dict)
    context_out: dict | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
```

```python
# backend/src/aura/core/domain/approval.py
from dataclasses import dataclass
from datetime import datetime

from aura.core.domain.enums import ActionCategory, ApprovalStatus


@dataclass
class Approval:
    id: int | None
    segment_id: int
    category: ActionCategory
    proposed_action: dict
    status: ApprovalStatus
    decided_by: int | None = None
    decided_at: datetime | None = None
```

```python
# backend/src/aura/core/domain/user.py
from dataclasses import dataclass

from aura.core.domain.enums import Role


@dataclass
class User:
    id: int | None
    username: str
    password_hash: str
    role: Role
```

```python
# backend/src/aura/core/domain/audit.py
from dataclasses import dataclass
from datetime import datetime


@dataclass
class AuditEntry:
    id: int | None
    job_id: int | None
    actor: str
    action: str
    payload: dict
    created_at: datetime
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/unit/test_domain.py -v`
Expected: 3 passed

- [ ] **Step 6: Commit**

```bash
git add backend/src/aura/core/domain backend/tests/unit/test_domain.py
git commit -m "feat: add core domain entities for jobs, segments and approvals"
```

---

### Task 3: Gate policy — default-deny classification

This is the system's core invariant. It is pure, deterministic, and never consults a model.

**Files:**
- Create: `backend/src/aura/core/policy/gate_policy.py`
- Test: `backend/tests/unit/test_gate_policy.py`

**Interfaces:**
- Consumes: `ActionCategory` (Task 2)
- Produces:
  - `TOOL_CATEGORIES: dict[str, ActionCategory]`
  - `classify(tool_name: str) -> ActionCategory`
  - `requires_approval(category: ActionCategory) -> bool`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_gate_policy.py
import pytest

from aura.core.domain.enums import ActionCategory
from aura.core.policy.gate_policy import classify, requires_approval


@pytest.mark.parametrize("tool,expected", [
    ("send_email", ActionCategory.OUTBOUND),
    ("create_invoice", ActionCategory.MONEY),
    ("draft_nda", ActionCategory.LEGAL),
    ("get_deal_status", ActionCategory.INTERNAL_READ),
    ("update_task_status", ActionCategory.INTERNAL_WRITE),
])
def test_known_tools_classify(tool, expected):
    assert classify(tool) is expected


def test_unknown_tool_is_unknown():
    assert classify("some_new_mcp_tool") is ActionCategory.UNKNOWN


@pytest.mark.parametrize("category", [
    ActionCategory.MONEY, ActionCategory.LEGAL,
    ActionCategory.OUTBOUND, ActionCategory.UNKNOWN,
])
def test_gated_categories_require_approval(category):
    assert requires_approval(category) is True


@pytest.mark.parametrize("category", [
    ActionCategory.INTERNAL_READ, ActionCategory.INTERNAL_WRITE,
])
def test_internal_categories_do_not_require_approval(category):
    assert requires_approval(category) is False


def test_unknown_tool_is_gated_end_to_end():
    """Default-deny: adding an MCP server cannot silently create an ungated path."""
    assert requires_approval(classify("brand_new_tool")) is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_gate_policy.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'aura.core.policy.gate_policy'`

- [ ] **Step 3: Write the implementation**

```python
# backend/src/aura/core/policy/gate_policy.py
"""Deterministic approval-gate classification. Never model-decided."""
from aura.core.domain.enums import ActionCategory

TOOL_CATEGORIES: dict[str, ActionCategory] = {
    "send_email": ActionCategory.OUTBOUND,
    "send_whatsapp": ActionCategory.OUTBOUND,
    "send_linkedin_message": ActionCategory.OUTBOUND,
    "create_invoice": ActionCategory.MONEY,
    "issue_refund": ActionCategory.MONEY,
    "record_payment": ActionCategory.MONEY,
    "draft_nda": ActionCategory.LEGAL,
    "draft_term_sheet": ActionCategory.LEGAL,
    "send_contract": ActionCategory.LEGAL,
    "get_deal_status": ActionCategory.INTERNAL_READ,
    "list_deals": ActionCategory.INTERNAL_READ,
    "search_notes": ActionCategory.INTERNAL_READ,
    "update_task_status": ActionCategory.INTERNAL_WRITE,
    "add_internal_note": ActionCategory.INTERNAL_WRITE,
}

_UNGATED = frozenset({ActionCategory.INTERNAL_READ, ActionCategory.INTERNAL_WRITE})


def classify(tool_name: str) -> ActionCategory:
    """Map a tool name to its action category. Unmapped tools are UNKNOWN."""
    return TOOL_CATEGORIES.get(tool_name, ActionCategory.UNKNOWN)


def requires_approval(category: ActionCategory) -> bool:
    """Default-deny: anything not explicitly internal requires human approval."""
    return category not in _UNGATED
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_gate_policy.py -v`
Expected: 10 passed

- [ ] **Step 5: Commit**

```bash
git add backend/src/aura/core/policy/gate_policy.py backend/tests/unit/test_gate_policy.py
git commit -m "feat: add default-deny approval gate policy"
```

---

### Task 4: RBAC policy

**Files:**
- Create: `backend/src/aura/core/policy/rbac_policy.py`
- Test: `backend/tests/unit/test_rbac_policy.py`

**Interfaces:**
- Consumes: `Role` (Task 2)
- Produces: `Capability` enum (`SUBMIT_JOB`, `DECIDE_APPROVAL`, `VIEW_ACTIVITY`, `MANAGE_USERS`); `can(role: Role, capability: Capability) -> bool`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_rbac_policy.py
from aura.core.domain.enums import Role
from aura.core.policy.rbac_policy import Capability, can


def test_admin_can_decide_approvals():
    assert can(Role.ADMIN, Capability.DECIDE_APPROVAL) is True


def test_member_cannot_decide_approvals():
    assert can(Role.MEMBER, Capability.DECIDE_APPROVAL) is False


def test_member_can_submit_jobs():
    assert can(Role.MEMBER, Capability.SUBMIT_JOB) is True


def test_member_cannot_manage_users():
    assert can(Role.MEMBER, Capability.MANAGE_USERS) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_rbac_policy.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

```python
# backend/src/aura/core/policy/rbac_policy.py
from enum import Enum

from aura.core.domain.enums import Role


class Capability(str, Enum):
    SUBMIT_JOB = "submit_job"
    DECIDE_APPROVAL = "decide_approval"
    VIEW_ACTIVITY = "view_activity"
    MANAGE_USERS = "manage_users"


_GRANTS: dict[Role, frozenset[Capability]] = {
    Role.ADMIN: frozenset(Capability),
    Role.MEMBER: frozenset({Capability.SUBMIT_JOB, Capability.VIEW_ACTIVITY}),
}


def can(role: Role, capability: Capability) -> bool:
    return capability in _GRANTS.get(role, frozenset())
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_rbac_policy.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add backend/src/aura/core/policy/rbac_policy.py backend/tests/unit/test_rbac_policy.py
git commit -m "feat: add role capability policy"
```

---

### Task 5: Core ports

**Files:**
- Create: `backend/src/aura/core/ports/repositories.py`, `orchestrator.py`, `events.py`
- Test: `backend/tests/unit/test_ports.py`

**Interfaces:**
- Produces (all `typing.Protocol`, runtime-checkable):
  - `JobRepository`: `add(job) -> Job`, `get(job_id) -> Job | None`, `update(job) -> Job`, `list_recent(limit: int) -> list[Job]`
  - `SegmentRepository`: `add(segment) -> Segment`, `get(segment_id) -> Segment | None`, `update(segment) -> Segment`, `claim_next_queued() -> Segment | None`, `list_for_job(job_id) -> list[Segment]`
  - `ApprovalRepository`: `add(approval) -> Approval`, `get(approval_id) -> Approval | None`, `update(approval) -> Approval`, `list_pending() -> list[Approval]`
  - `AuditRepository`: `append(entry) -> AuditEntry`, `list_recent(limit: int) -> list[AuditEntry]` (**no update/delete**)
  - `UserRepository`: `get_by_username(username) -> User | None`, `get(user_id) -> User | None`
  - `Orchestrator`: `run(context_in: dict) -> OrchestratorResult`
  - `OrchestratorResult` dataclass: `completed: bool`, `context_out: dict`, `proposed_action: ProposedAction | None`
  - `EventPublisher`: `publish(event_type: str, payload: dict) -> None`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_ports.py
from aura.core.ports.orchestrator import Orchestrator, OrchestratorResult


class StubOrchestrator:
    def run(self, context_in: dict) -> OrchestratorResult:
        return OrchestratorResult(completed=True, context_out={"ok": True}, proposed_action=None)


def test_stub_satisfies_orchestrator_protocol():
    assert isinstance(StubOrchestrator(), Orchestrator)


def test_orchestrator_result_carries_no_action_when_complete():
    result = StubOrchestrator().run({})
    assert result.completed is True
    assert result.proposed_action is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_ports.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'aura.core.ports.orchestrator'`

- [ ] **Step 3: Write `orchestrator.py`**

```python
# backend/src/aura/core/ports/orchestrator.py
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from aura.core.domain.segment import ProposedAction


@dataclass
class OrchestratorResult:
    """Outcome of running one segment.

    completed=True  -> job is finished; proposed_action is None.
    completed=False -> an action needs approval; proposed_action is set.
    """
    completed: bool
    context_out: dict
    proposed_action: ProposedAction | None


@runtime_checkable
class Orchestrator(Protocol):
    def run(self, context_in: dict) -> OrchestratorResult: ...
```

- [ ] **Step 4: Write `repositories.py` and `events.py`**

```python
# backend/src/aura/core/ports/repositories.py
from typing import Protocol, runtime_checkable

from aura.core.domain.approval import Approval
from aura.core.domain.audit import AuditEntry
from aura.core.domain.job import Job
from aura.core.domain.segment import Segment
from aura.core.domain.user import User


@runtime_checkable
class JobRepository(Protocol):
    def add(self, job: Job) -> Job: ...
    def get(self, job_id: int) -> Job | None: ...
    def update(self, job: Job) -> Job: ...
    def list_recent(self, limit: int = 50) -> list[Job]: ...


@runtime_checkable
class SegmentRepository(Protocol):
    def add(self, segment: Segment) -> Segment: ...
    def get(self, segment_id: int) -> Segment | None: ...
    def update(self, segment: Segment) -> Segment: ...
    def claim_next_queued(self) -> Segment | None: ...
    def list_for_job(self, job_id: int) -> list[Segment]: ...


@runtime_checkable
class ApprovalRepository(Protocol):
    def add(self, approval: Approval) -> Approval: ...
    def get(self, approval_id: int) -> Approval | None: ...
    def update(self, approval: Approval) -> Approval: ...
    def list_pending(self) -> list[Approval]: ...


@runtime_checkable
class AuditRepository(Protocol):
    """Append-only. No update or delete exists by design."""
    def append(self, entry: AuditEntry) -> AuditEntry: ...
    def list_recent(self, limit: int = 100) -> list[AuditEntry]: ...


@runtime_checkable
class UserRepository(Protocol):
    def get_by_username(self, username: str) -> User | None: ...
    def get(self, user_id: int) -> User | None: ...
```

```python
# backend/src/aura/core/ports/events.py
from typing import Protocol, runtime_checkable


@runtime_checkable
class EventPublisher(Protocol):
    def publish(self, event_type: str, payload: dict) -> None: ...
```

- [ ] **Step 5: Run tests and the import contract**

```bash
uv run pytest tests/unit -v
uv run lint-imports --config .importlinter
```

Expected: all tests pass; contract KEPT.

- [ ] **Step 6: Commit**

```bash
git add backend/src/aura/core/ports backend/tests/unit/test_ports.py
git commit -m "feat: define core ports for repositories, orchestration and events"
```

---

### Task 6: Use case — submit_job

**Files:**
- Create: `backend/src/aura/core/services/submit_job.py`
- Test: `backend/tests/unit/test_submit_job.py`, `backend/tests/unit/fakes.py`

**Interfaces:**
- Consumes: Task 2 entities, Task 5 ports
- Produces: `submit_job(inputs: dict, deal_id: int | None, actor: str, jobs: JobRepository, segments: SegmentRepository, audit: AuditRepository, events: EventPublisher) -> Job`

- [ ] **Step 1: Write in-memory fakes**

```python
# backend/tests/unit/fakes.py
from aura.core.domain.approval import Approval
from aura.core.domain.audit import AuditEntry
from aura.core.domain.enums import SegmentStatus
from aura.core.domain.job import Job
from aura.core.domain.segment import Segment


class FakeJobRepo:
    def __init__(self):
        self.items: dict[int, Job] = {}
        self._next = 1

    def add(self, job: Job) -> Job:
        job.id = self._next
        self._next += 1
        self.items[job.id] = job
        return job

    def get(self, job_id: int) -> Job | None:
        return self.items.get(job_id)

    def update(self, job: Job) -> Job:
        self.items[job.id] = job
        return job

    def list_recent(self, limit: int = 50) -> list[Job]:
        return list(self.items.values())[-limit:]


class FakeSegmentRepo:
    def __init__(self):
        self.items: dict[int, Segment] = {}
        self._next = 1

    def add(self, segment: Segment) -> Segment:
        segment.id = self._next
        self._next += 1
        self.items[segment.id] = segment
        return segment

    def get(self, segment_id: int) -> Segment | None:
        return self.items.get(segment_id)

    def update(self, segment: Segment) -> Segment:
        self.items[segment.id] = segment
        return segment

    def claim_next_queued(self) -> Segment | None:
        for seg in self.items.values():
            if seg.status is SegmentStatus.QUEUED:
                return seg
        return None

    def list_for_job(self, job_id: int) -> list[Segment]:
        return [s for s in self.items.values() if s.job_id == job_id]


class FakeApprovalRepo:
    def __init__(self):
        self.items: dict[int, Approval] = {}
        self._next = 1

    def add(self, approval: Approval) -> Approval:
        approval.id = self._next
        self._next += 1
        self.items[approval.id] = approval
        return approval

    def get(self, approval_id: int) -> Approval | None:
        return self.items.get(approval_id)

    def update(self, approval: Approval) -> Approval:
        self.items[approval.id] = approval
        return approval

    def list_pending(self) -> list[Approval]:
        from aura.core.domain.enums import ApprovalStatus
        return [a for a in self.items.values() if a.status is ApprovalStatus.PENDING]


class FakeAuditRepo:
    def __init__(self):
        self.entries: list[AuditEntry] = []

    def append(self, entry: AuditEntry) -> AuditEntry:
        entry.id = len(self.entries) + 1
        self.entries.append(entry)
        return entry

    def list_recent(self, limit: int = 100) -> list[AuditEntry]:
        return self.entries[-limit:]


class FakeEvents:
    def __init__(self):
        self.published: list[tuple[str, dict]] = []

    def publish(self, event_type: str, payload: dict) -> None:
        self.published.append((event_type, payload))
```

- [ ] **Step 2: Write the failing test**

```python
# backend/tests/unit/test_submit_job.py
from aura.core.domain.enums import JobStatus, SegmentStatus
from aura.core.services.submit_job import submit_job
from tests.unit.fakes import FakeAuditRepo, FakeEvents, FakeJobRepo, FakeSegmentRepo


def test_submit_creates_job_and_first_segment():
    jobs, segments, audit, events = FakeJobRepo(), FakeSegmentRepo(), FakeAuditRepo(), FakeEvents()

    job = submit_job(inputs={"brief": "draft intro to D-002"}, deal_id=2, actor="bhavesh",
                     jobs=jobs, segments=segments, audit=audit, events=events)

    assert job.id == 1
    assert job.status is JobStatus.PENDING

    segs = segments.list_for_job(job.id)
    assert len(segs) == 1
    assert segs[0].seq == 1
    assert segs[0].status is SegmentStatus.QUEUED
    assert segs[0].context_in == {"brief": "draft intro to D-002"}


def test_submit_writes_audit_entry():
    jobs, segments, audit, events = FakeJobRepo(), FakeSegmentRepo(), FakeAuditRepo(), FakeEvents()
    submit_job(inputs={}, deal_id=None, actor="bhavesh",
               jobs=jobs, segments=segments, audit=audit, events=events)
    assert audit.entries[0].action == "job_submitted"
    assert audit.entries[0].actor == "bhavesh"


def test_submit_publishes_event():
    jobs, segments, audit, events = FakeJobRepo(), FakeSegmentRepo(), FakeAuditRepo(), FakeEvents()
    submit_job(inputs={}, deal_id=None, actor="bhavesh",
               jobs=jobs, segments=segments, audit=audit, events=events)
    assert events.published[0][0] == "job_submitted"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_submit_job.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'aura.core.services.submit_job'`

- [ ] **Step 4: Write the implementation**

```python
# backend/src/aura/core/services/submit_job.py
from datetime import datetime, timezone

from aura.core.domain.audit import AuditEntry
from aura.core.domain.enums import JobStatus, SegmentStatus
from aura.core.domain.job import Job
from aura.core.domain.segment import Segment
from aura.core.ports.events import EventPublisher
from aura.core.ports.repositories import AuditRepository, JobRepository, SegmentRepository


def submit_job(
    inputs: dict,
    deal_id: int | None,
    actor: str,
    jobs: JobRepository,
    segments: SegmentRepository,
    audit: AuditRepository,
    events: EventPublisher,
) -> Job:
    """Create a job and queue its first segment. Returns immediately — no inference here."""
    now = datetime.now(timezone.utc)

    job = jobs.add(Job(id=None, status=JobStatus.PENDING, inputs=inputs,
                       deal_id=deal_id, result=None, created_at=now))

    segments.add(Segment(id=None, job_id=job.id, seq=1, status=SegmentStatus.QUEUED,
                         context_in=dict(inputs), context_out=None,
                         started_at=None, ended_at=None))

    audit.append(AuditEntry(id=None, job_id=job.id, actor=actor, action="job_submitted",
                            payload={"inputs": inputs, "deal_id": deal_id}, created_at=now))

    events.publish("job_submitted", {"job_id": job.id})
    return job
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/unit/test_submit_job.py -v`
Expected: 3 passed

- [ ] **Step 6: Commit**

```bash
git add backend/src/aura/core/services/submit_job.py backend/tests/unit/test_submit_job.py backend/tests/unit/fakes.py
git commit -m "feat: add submit_job use case with audit and event emission"
```

---

### Task 7: Use case — run_segment (the heart)

**Files:**
- Create: `backend/src/aura/core/services/run_segment.py`
- Test: `backend/tests/unit/test_run_segment.py`

**Interfaces:**
- Consumes: `Orchestrator`, `OrchestratorResult` (Task 5), gate policy (Task 3)
- Produces: `run_segment(segment_id: int, orchestrator: Orchestrator, jobs, segments, approvals, audit, events) -> None`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_run_segment.py
from datetime import datetime, timezone

from aura.core.domain.enums import (ActionCategory, ApprovalStatus, JobStatus,
                                    SegmentStatus)
from aura.core.domain.job import Job
from aura.core.domain.segment import ProposedAction, Segment
from aura.core.ports.orchestrator import OrchestratorResult
from aura.core.services.run_segment import run_segment
from tests.unit.fakes import (FakeApprovalRepo, FakeAuditRepo, FakeEvents,
                              FakeJobRepo, FakeSegmentRepo)


class CompletingOrchestrator:
    def run(self, context_in: dict) -> OrchestratorResult:
        return OrchestratorResult(completed=True, context_out={"draft": "hello"},
                                  proposed_action=None)


class GatingOrchestrator:
    def run(self, context_in: dict) -> OrchestratorResult:
        return OrchestratorResult(
            completed=False,
            context_out={"draft": "Dear Ravi..."},
            proposed_action=ProposedAction(tool="send_email",
                                           category=ActionCategory.OUTBOUND,
                                           arguments={"to": "ravi@x.com"},
                                           summary="Send intro email"),
        )


def _seed():
    jobs, segments = FakeJobRepo(), FakeSegmentRepo()
    approvals, audit, events = FakeApprovalRepo(), FakeAuditRepo(), FakeEvents()
    job = jobs.add(Job(id=None, status=JobStatus.PENDING, inputs={}, deal_id=None,
                       result=None, created_at=datetime.now(timezone.utc)))
    seg = segments.add(Segment(id=None, job_id=job.id, seq=1, status=SegmentStatus.QUEUED,
                               context_in={}, context_out=None, started_at=None, ended_at=None))
    return job, seg, jobs, segments, approvals, audit, events


def test_completing_run_marks_job_complete():
    job, seg, jobs, segments, approvals, audit, events = _seed()

    run_segment(seg.id, CompletingOrchestrator(), jobs, segments, approvals, audit, events)

    assert segments.get(seg.id).status is SegmentStatus.DONE
    assert jobs.get(job.id).status is JobStatus.COMPLETE
    assert approvals.list_pending() == []


def test_gated_run_ends_segment_and_creates_approval():
    job, seg, jobs, segments, approvals, audit, events = _seed()

    run_segment(seg.id, GatingOrchestrator(), jobs, segments, approvals, audit, events)

    updated = segments.get(seg.id)
    assert updated.status is SegmentStatus.AWAITING_APPROVAL
    assert updated.context_out == {"draft": "Dear Ravi..."}
    assert jobs.get(job.id).status is JobStatus.AWAITING_APPROVAL

    pending = approvals.list_pending()
    assert len(pending) == 1
    assert pending[0].category is ActionCategory.OUTBOUND
    assert pending[0].status is ApprovalStatus.PENDING


def test_gated_run_publishes_approval_required():
    _, seg, jobs, segments, approvals, audit, events = _seed()
    run_segment(seg.id, GatingOrchestrator(), jobs, segments, approvals, audit, events)
    assert any(e[0] == "approval_required" for e in events.published)


def test_no_second_segment_is_created_before_approval():
    job, seg, jobs, segments, approvals, audit, events = _seed()
    run_segment(seg.id, GatingOrchestrator(), jobs, segments, approvals, audit, events)
    assert len(segments.list_for_job(job.id)) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_run_segment.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'aura.core.services.run_segment'`

- [ ] **Step 3: Write the implementation**

```python
# backend/src/aura/core/services/run_segment.py
from dataclasses import asdict
from datetime import datetime, timezone

from aura.core.domain.approval import Approval
from aura.core.domain.audit import AuditEntry
from aura.core.domain.enums import ApprovalStatus, JobStatus, SegmentStatus
from aura.core.policy.gate_policy import requires_approval
from aura.core.ports.events import EventPublisher
from aura.core.ports.orchestrator import Orchestrator
from aura.core.ports.repositories import (ApprovalRepository, AuditRepository,
                                          JobRepository, SegmentRepository)


def run_segment(
    segment_id: int,
    orchestrator: Orchestrator,
    jobs: JobRepository,
    segments: SegmentRepository,
    approvals: ApprovalRepository,
    audit: AuditRepository,
    events: EventPublisher,
) -> None:
    """Run one segment to completion or to a gate. Never blocks on a human."""
    segment = segments.get(segment_id)
    if segment is None:
        raise ValueError(f"segment {segment_id} not found")

    job = jobs.get(segment.job_id)
    now = datetime.now(timezone.utc)

    segment.status = SegmentStatus.RUNNING
    segment.started_at = now
    segments.update(segment)
    job.status = JobStatus.RUNNING
    jobs.update(job)

    try:
        result = orchestrator.run(segment.context_in)
    except Exception as exc:
        segment.status = SegmentStatus.FAILED
        segment.ended_at = datetime.now(timezone.utc)
        segments.update(segment)
        job.status = JobStatus.FAILED
        jobs.update(job)
        audit.append(AuditEntry(id=None, job_id=job.id, actor="system",
                                action="segment_failed",
                                payload={"segment_id": segment.id, "error": str(exc)},
                                created_at=datetime.now(timezone.utc)))
        events.publish("job_failed", {"job_id": job.id})
        return

    ended = datetime.now(timezone.utc)
    segment.context_out = result.context_out
    segment.ended_at = ended

    action = result.proposed_action
    if action is not None and requires_approval(action.category):
        segment.status = SegmentStatus.AWAITING_APPROVAL
        segments.update(segment)

        approval = approvals.add(Approval(id=None, segment_id=segment.id,
                                          category=action.category,
                                          proposed_action=asdict(action),
                                          status=ApprovalStatus.PENDING))
        job.status = JobStatus.AWAITING_APPROVAL
        jobs.update(job)

        audit.append(AuditEntry(id=None, job_id=job.id, actor="system",
                                action="approval_requested",
                                payload={"approval_id": approval.id,
                                         "category": action.category.value,
                                         "summary": action.summary},
                                created_at=ended))
        events.publish("approval_required",
                       {"job_id": job.id, "approval_id": approval.id,
                        "category": action.category.value, "summary": action.summary})
        return

    segment.status = SegmentStatus.DONE
    segments.update(segment)
    job.status = JobStatus.COMPLETE
    job.result = result.context_out
    jobs.update(job)

    audit.append(AuditEntry(id=None, job_id=job.id, actor="system", action="job_completed",
                            payload={"segment_id": segment.id}, created_at=ended))
    events.publish("job_complete", {"job_id": job.id})
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_run_segment.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add backend/src/aura/core/services/run_segment.py backend/tests/unit/test_run_segment.py
git commit -m "feat: add segmented run_segment use case that ends at approval gates"
```

---

### Task 8: Use case — decide_approval

**Files:**
- Create: `backend/src/aura/core/services/decide_approval.py`
- Test: `backend/tests/unit/test_decide_approval.py`

**Interfaces:**
- Produces: `decide_approval(approval_id: int, approved: bool, user_id: int, actor: str, jobs, segments, approvals, audit, events) -> Approval`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_decide_approval.py
from datetime import datetime, timezone

import pytest

from aura.core.domain.approval import Approval
from aura.core.domain.enums import (ActionCategory, ApprovalStatus, JobStatus,
                                    SegmentStatus)
from aura.core.domain.job import Job
from aura.core.domain.segment import Segment
from aura.core.services.decide_approval import decide_approval
from tests.unit.fakes import (FakeApprovalRepo, FakeAuditRepo, FakeEvents,
                              FakeJobRepo, FakeSegmentRepo)


def _seed_awaiting():
    jobs, segments = FakeJobRepo(), FakeSegmentRepo()
    approvals, audit, events = FakeApprovalRepo(), FakeAuditRepo(), FakeEvents()
    job = jobs.add(Job(id=None, status=JobStatus.AWAITING_APPROVAL, inputs={},
                       deal_id=None, result=None, created_at=datetime.now(timezone.utc)))
    seg = segments.add(Segment(id=None, job_id=job.id, seq=1,
                               status=SegmentStatus.AWAITING_APPROVAL,
                               context_in={}, context_out={"draft": "hi"},
                               started_at=None, ended_at=None))
    appr = approvals.add(Approval(id=None, segment_id=seg.id,
                                  category=ActionCategory.OUTBOUND,
                                  proposed_action={"tool": "send_email"},
                                  status=ApprovalStatus.PENDING))
    return job, seg, appr, jobs, segments, approvals, audit, events


def test_approve_spawns_next_segment_seeded_from_context_out():
    job, seg, appr, jobs, segments, approvals, audit, events = _seed_awaiting()

    decide_approval(appr.id, approved=True, user_id=1, actor="bhavesh",
                    jobs=jobs, segments=segments, approvals=approvals,
                    audit=audit, events=events)

    segs = sorted(segments.list_for_job(job.id), key=lambda s: s.seq)
    assert len(segs) == 2
    assert segs[1].seq == 2
    assert segs[1].status is SegmentStatus.QUEUED
    assert segs[1].context_in == {"draft": "hi"}
    assert approvals.get(appr.id).status is ApprovalStatus.APPROVED


def test_reject_marks_job_rejected_and_creates_no_segment():
    job, seg, appr, jobs, segments, approvals, audit, events = _seed_awaiting()

    decide_approval(appr.id, approved=False, user_id=1, actor="bhavesh",
                    jobs=jobs, segments=segments, approvals=approvals,
                    audit=audit, events=events)

    assert approvals.get(appr.id).status is ApprovalStatus.REJECTED
    assert jobs.get(job.id).status is JobStatus.REJECTED
    assert len(segments.list_for_job(job.id)) == 1


def test_decision_is_audited_with_deciding_user():
    _, _, appr, jobs, segments, approvals, audit, events = _seed_awaiting()
    decide_approval(appr.id, approved=True, user_id=7, actor="bhavesh",
                    jobs=jobs, segments=segments, approvals=approvals,
                    audit=audit, events=events)
    entry = audit.entries[-1]
    assert entry.action == "approval_decided"
    assert entry.payload["approved"] is True
    assert entry.payload["decided_by"] == 7


def test_deciding_twice_raises():
    _, _, appr, jobs, segments, approvals, audit, events = _seed_awaiting()
    decide_approval(appr.id, True, 1, "bhavesh", jobs, segments, approvals, audit, events)
    with pytest.raises(ValueError):
        decide_approval(appr.id, True, 1, "bhavesh", jobs, segments, approvals, audit, events)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_decide_approval.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

```python
# backend/src/aura/core/services/decide_approval.py
from datetime import datetime, timezone

from aura.core.domain.approval import Approval
from aura.core.domain.audit import AuditEntry
from aura.core.domain.enums import ApprovalStatus, JobStatus, SegmentStatus
from aura.core.domain.segment import Segment
from aura.core.ports.events import EventPublisher
from aura.core.ports.repositories import (ApprovalRepository, AuditRepository,
                                          JobRepository, SegmentRepository)


def decide_approval(
    approval_id: int,
    approved: bool,
    user_id: int,
    actor: str,
    jobs: JobRepository,
    segments: SegmentRepository,
    approvals: ApprovalRepository,
    audit: AuditRepository,
    events: EventPublisher,
) -> Approval:
    """Record a human decision. On approval, queue the next segment seeded from context_out."""
    approval = approvals.get(approval_id)
    if approval is None:
        raise ValueError(f"approval {approval_id} not found")
    if approval.status is not ApprovalStatus.PENDING:
        raise ValueError(f"approval {approval_id} already decided")

    now = datetime.now(timezone.utc)
    segment = segments.get(approval.segment_id)
    job = jobs.get(segment.job_id)

    approval.status = ApprovalStatus.APPROVED if approved else ApprovalStatus.REJECTED
    approval.decided_by = user_id
    approval.decided_at = now
    approvals.update(approval)

    segment.status = SegmentStatus.DONE
    segments.update(segment)

    if approved:
        segments.add(Segment(id=None, job_id=job.id, seq=segment.seq + 1,
                             status=SegmentStatus.QUEUED,
                             context_in=dict(segment.context_out or {}),
                             context_out=None, started_at=None, ended_at=None))
        job.status = JobStatus.PENDING
    else:
        job.status = JobStatus.REJECTED
    jobs.update(job)

    audit.append(AuditEntry(id=None, job_id=job.id, actor=actor, action="approval_decided",
                            payload={"approval_id": approval.id, "approved": approved,
                                     "decided_by": user_id},
                            created_at=now))
    events.publish("approval_decided",
                   {"job_id": job.id, "approval_id": approval.id, "approved": approved})
    return approval
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit -v && uv run lint-imports --config .importlinter`
Expected: all pass; contract KEPT.

- [ ] **Step 5: Commit**

```bash
git add backend/src/aura/core/services/decide_approval.py backend/tests/unit/test_decide_approval.py
git commit -m "feat: add decide_approval use case that resumes jobs via a new segment"
```

---

### Task 9: Data layer — engine, ORM models, mappers, repositories

**Files:**
- Create: `backend/src/aura/config.py`, `backend/src/aura/data/engine.py`, `backend/src/aura/data/models/tables.py`, `backend/src/aura/data/mappers.py`, `backend/src/aura/data/repositories/sql.py`
- Test: `backend/tests/integration/test_repositories.py`, `backend/tests/integration/__init__.py`

**Interfaces:**
- Consumes: domain entities (Task 2), port protocols (Task 5)
- Produces: `Settings` (pydantic-settings, fields `database_url: str = "sqlite:///./aura.db"`, `jwt_secret: str = "dev-secret-change-me"`, `jwt_ttl_minutes: int = 480`, `ollama_base_url: str = "http://localhost:11434"`, `ollama_model: str = "qwen2.5:1.5b"`); `get_settings()`; `make_engine(url)`; `SessionLocal`; `Base`; ORM tables `UserRow`, `JobRow`, `SegmentRow`, `ApprovalRow`, `AuditRow`, `DealRow`; `SqlJobRepository`, `SqlSegmentRepository`, `SqlApprovalRepository`, `SqlAuditRepository`, `SqlUserRepository` — each taking a `Session` in `__init__`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/integration/test_repositories.py
from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import Session

from aura.core.domain.enums import JobStatus, SegmentStatus
from aura.core.domain.job import Job
from aura.core.domain.segment import Segment
from aura.data.engine import Base, make_engine
from aura.data.repositories.sql import SqlJobRepository, SqlSegmentRepository


@pytest.fixture()
def session():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def test_job_roundtrips_as_domain_object(session):
    repo = SqlJobRepository(session)
    saved = repo.add(Job(id=None, status=JobStatus.PENDING, inputs={"brief": "x"},
                         deal_id=None, result=None, created_at=datetime.now(timezone.utc)))
    assert saved.id is not None

    fetched = repo.get(saved.id)
    assert isinstance(fetched, Job)
    assert fetched.inputs == {"brief": "x"}
    assert fetched.status is JobStatus.PENDING


def test_claim_next_queued_returns_only_queued_segments(session):
    jobs, segs = SqlJobRepository(session), SqlSegmentRepository(session)
    job = jobs.add(Job(id=None, status=JobStatus.PENDING, inputs={}, deal_id=None,
                       result=None, created_at=datetime.now(timezone.utc)))
    segs.add(Segment(id=None, job_id=job.id, seq=1, status=SegmentStatus.DONE,
                     context_in={}, context_out={}, started_at=None, ended_at=None))
    queued = segs.add(Segment(id=None, job_id=job.id, seq=2, status=SegmentStatus.QUEUED,
                              context_in={"a": 1}, context_out=None,
                              started_at=None, ended_at=None))

    claimed = segs.claim_next_queued()
    assert claimed.id == queued.id
    assert claimed.context_in == {"a": 1}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/test_repositories.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'aura.data.engine'`

- [ ] **Step 3: Write `config.py` and `engine.py`**

```python
# backend/src/aura/config.py
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="AURA_", extra="ignore")

    database_url: str = "sqlite:///./aura.db"
    jwt_secret: str = "dev-secret-change-me"
    jwt_ttl_minutes: int = 480
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:1.5b"


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

```python
# backend/src/aura/data/engine.py
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from aura.config import get_settings


class Base(DeclarativeBase):
    pass


def make_engine(url: str | None = None):
    url = url or get_settings().database_url
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, connect_args=connect_args, future=True)


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)
```

- [ ] **Step 4: Write `models/tables.py`**

```python
# backend/src/aura/data/models/tables.py
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from aura.data.engine import Base


class UserRow(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16))


class DealRow(Base):
    __tablename__ = "deals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    external_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    stage: Mapped[str] = mapped_column(String(64))
    owner: Mapped[str] = mapped_column(String(64))


class JobRow(Base):
    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    inputs: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    deal_id: Mapped[int | None] = mapped_column(ForeignKey("deals.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SegmentRow(Base):
    __tablename__ = "segments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), index=True)
    context_in: Mapped[dict] = mapped_column(JSON, default=dict)
    context_out: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ApprovalRow(Base):
    __tablename__ = "approvals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    segment_id: Mapped[int] = mapped_column(ForeignKey("segments.id"), index=True)
    category: Mapped[str] = mapped_column(String(32))
    proposed_action: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), index=True)
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditRow(Base):
    __tablename__ = "audit_entries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id"), nullable=True, index=True)
    actor: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(64), index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
```

- [ ] **Step 5: Write `mappers.py`**

```python
# backend/src/aura/data/mappers.py
"""ORM <-> domain translation. ORM rows never escape the data package."""
from aura.core.domain.approval import Approval
from aura.core.domain.audit import AuditEntry
from aura.core.domain.enums import (ActionCategory, ApprovalStatus, JobStatus,
                                    Role, SegmentStatus)
from aura.core.domain.job import Job
from aura.core.domain.segment import Segment
from aura.core.domain.user import User
from aura.data.models.tables import (ApprovalRow, AuditRow, JobRow, SegmentRow,
                                     UserRow)


def job_to_domain(row: JobRow) -> Job:
    return Job(id=row.id, status=JobStatus(row.status), inputs=row.inputs or {},
               deal_id=row.deal_id, result=row.result, created_at=row.created_at)


def segment_to_domain(row: SegmentRow) -> Segment:
    return Segment(id=row.id, job_id=row.job_id, seq=row.seq,
                   status=SegmentStatus(row.status), context_in=row.context_in or {},
                   context_out=row.context_out, started_at=row.started_at,
                   ended_at=row.ended_at)


def approval_to_domain(row: ApprovalRow) -> Approval:
    return Approval(id=row.id, segment_id=row.segment_id,
                    category=ActionCategory(row.category),
                    proposed_action=row.proposed_action or {},
                    status=ApprovalStatus(row.status), decided_by=row.decided_by,
                    decided_at=row.decided_at)


def audit_to_domain(row: AuditRow) -> AuditEntry:
    return AuditEntry(id=row.id, job_id=row.job_id, actor=row.actor, action=row.action,
                      payload=row.payload or {}, created_at=row.created_at)


def user_to_domain(row: UserRow) -> User:
    return User(id=row.id, username=row.username, password_hash=row.password_hash,
                role=Role(row.role))
```

- [ ] **Step 6: Write `repositories/sql.py`**

```python
# backend/src/aura/data/repositories/sql.py
from sqlalchemy import select
from sqlalchemy.orm import Session

from aura.core.domain.approval import Approval
from aura.core.domain.audit import AuditEntry
from aura.core.domain.enums import ApprovalStatus, SegmentStatus
from aura.core.domain.job import Job
from aura.core.domain.segment import Segment
from aura.core.domain.user import User
from aura.data import mappers
from aura.data.models.tables import (ApprovalRow, AuditRow, JobRow, SegmentRow,
                                     UserRow)


class SqlJobRepository:
    def __init__(self, session: Session):
        self.s = session

    def add(self, job: Job) -> Job:
        row = JobRow(status=job.status.value, inputs=job.inputs, result=job.result,
                     deal_id=job.deal_id, created_at=job.created_at)
        self.s.add(row)
        self.s.commit()
        self.s.refresh(row)
        return mappers.job_to_domain(row)

    def get(self, job_id: int) -> Job | None:
        row = self.s.get(JobRow, job_id)
        return mappers.job_to_domain(row) if row else None

    def update(self, job: Job) -> Job:
        row = self.s.get(JobRow, job.id)
        row.status, row.result = job.status.value, job.result
        self.s.commit()
        self.s.refresh(row)
        return mappers.job_to_domain(row)

    def list_recent(self, limit: int = 50) -> list[Job]:
        rows = self.s.scalars(select(JobRow).order_by(JobRow.id.desc()).limit(limit)).all()
        return [mappers.job_to_domain(r) for r in rows]


class SqlSegmentRepository:
    def __init__(self, session: Session):
        self.s = session

    def add(self, segment: Segment) -> Segment:
        row = SegmentRow(job_id=segment.job_id, seq=segment.seq, status=segment.status.value,
                         context_in=segment.context_in, context_out=segment.context_out,
                         started_at=segment.started_at, ended_at=segment.ended_at)
        self.s.add(row)
        self.s.commit()
        self.s.refresh(row)
        return mappers.segment_to_domain(row)

    def get(self, segment_id: int) -> Segment | None:
        row = self.s.get(SegmentRow, segment_id)
        return mappers.segment_to_domain(row) if row else None

    def update(self, segment: Segment) -> Segment:
        row = self.s.get(SegmentRow, segment.id)
        row.status = segment.status.value
        row.context_out = segment.context_out
        row.started_at, row.ended_at = segment.started_at, segment.ended_at
        self.s.commit()
        self.s.refresh(row)
        return mappers.segment_to_domain(row)

    def claim_next_queued(self) -> Segment | None:
        row = self.s.scalars(
            select(SegmentRow).where(SegmentRow.status == SegmentStatus.QUEUED.value)
            .order_by(SegmentRow.id.asc()).limit(1)
        ).first()
        return mappers.segment_to_domain(row) if row else None

    def list_for_job(self, job_id: int) -> list[Segment]:
        rows = self.s.scalars(
            select(SegmentRow).where(SegmentRow.job_id == job_id).order_by(SegmentRow.seq)
        ).all()
        return [mappers.segment_to_domain(r) for r in rows]


class SqlApprovalRepository:
    def __init__(self, session: Session):
        self.s = session

    def add(self, approval: Approval) -> Approval:
        row = ApprovalRow(segment_id=approval.segment_id, category=approval.category.value,
                          proposed_action=approval.proposed_action,
                          status=approval.status.value, decided_by=approval.decided_by,
                          decided_at=approval.decided_at)
        self.s.add(row)
        self.s.commit()
        self.s.refresh(row)
        return mappers.approval_to_domain(row)

    def get(self, approval_id: int) -> Approval | None:
        row = self.s.get(ApprovalRow, approval_id)
        return mappers.approval_to_domain(row) if row else None

    def update(self, approval: Approval) -> Approval:
        row = self.s.get(ApprovalRow, approval.id)
        row.status = approval.status.value
        row.decided_by, row.decided_at = approval.decided_by, approval.decided_at
        self.s.commit()
        self.s.refresh(row)
        return mappers.approval_to_domain(row)

    def list_pending(self) -> list[Approval]:
        rows = self.s.scalars(
            select(ApprovalRow).where(ApprovalRow.status == ApprovalStatus.PENDING.value)
            .order_by(ApprovalRow.id.desc())
        ).all()
        return [mappers.approval_to_domain(r) for r in rows]


class SqlAuditRepository:
    """Append-only by design — no update or delete method exists."""

    def __init__(self, session: Session):
        self.s = session

    def append(self, entry: AuditEntry) -> AuditEntry:
        row = AuditRow(job_id=entry.job_id, actor=entry.actor, action=entry.action,
                       payload=entry.payload, created_at=entry.created_at)
        self.s.add(row)
        self.s.commit()
        self.s.refresh(row)
        return mappers.audit_to_domain(row)

    def list_recent(self, limit: int = 100) -> list[AuditEntry]:
        rows = self.s.scalars(select(AuditRow).order_by(AuditRow.id.desc()).limit(limit)).all()
        return [mappers.audit_to_domain(r) for r in rows]


class SqlUserRepository:
    def __init__(self, session: Session):
        self.s = session

    def get_by_username(self, username: str) -> User | None:
        row = self.s.scalars(select(UserRow).where(UserRow.username == username)).first()
        return mappers.user_to_domain(row) if row else None

    def get(self, user_id: int) -> User | None:
        row = self.s.get(UserRow, user_id)
        return mappers.user_to_domain(row) if row else None
```

- [ ] **Step 7: Run tests**

```bash
uv run pytest tests -v
uv run lint-imports --config .importlinter
```

Expected: all pass; contract KEPT (proves core still has no SQLAlchemy import).

- [ ] **Step 8: Commit**

```bash
git add backend/src/aura/config.py backend/src/aura/data backend/tests/integration
git commit -m "feat: add SQLite data layer with domain mapping and repositories"
```

---

### Task 10: Auth — password hashing, JWT, and the authenticate use case

**Files:**
- Create: `backend/src/aura/core/services/authenticate.py`, `backend/src/aura/api/security.py`
- Test: `backend/tests/unit/test_authenticate.py`

**Interfaces:**
- Produces: `authenticate(username, password, users: UserRepository, verify: Callable[[str, str], bool]) -> User | None`; `hash_password(p) -> str`; `verify_password(plain, hashed) -> bool`; `create_token(user) -> str`; `decode_token(token) -> dict`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_authenticate.py
from aura.core.domain.enums import Role
from aura.core.domain.user import User
from aura.core.services.authenticate import authenticate


class FakeUserRepo:
    def __init__(self, user: User | None):
        self.user = user

    def get_by_username(self, username: str) -> User | None:
        return self.user if self.user and self.user.username == username else None

    def get(self, user_id: int) -> User | None:
        return self.user


def always_true(plain: str, hashed: str) -> bool:
    return True


def always_false(plain: str, hashed: str) -> bool:
    return False


def test_authenticate_returns_user_on_valid_password():
    user = User(id=1, username="bhavesh", password_hash="x", role=Role.ADMIN)
    assert authenticate("bhavesh", "pw", FakeUserRepo(user), always_true) == user


def test_authenticate_returns_none_on_bad_password():
    user = User(id=1, username="bhavesh", password_hash="x", role=Role.ADMIN)
    assert authenticate("bhavesh", "pw", FakeUserRepo(user), always_false) is None


def test_authenticate_returns_none_for_unknown_user():
    assert authenticate("nobody", "pw", FakeUserRepo(None), always_true) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_authenticate.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write `authenticate.py` (pure — hashing is injected)**

```python
# backend/src/aura/core/services/authenticate.py
from typing import Callable

from aura.core.domain.user import User
from aura.core.ports.repositories import UserRepository


def authenticate(
    username: str,
    password: str,
    users: UserRepository,
    verify: Callable[[str, str], bool],
) -> User | None:
    """Return the user when credentials are valid, else None. No framework imports."""
    user = users.get_by_username(username)
    if user is None:
        return None
    if not verify(password, user.password_hash):
        return None
    return user
```

- [ ] **Step 4: Write `api/security.py` (adapter — bcrypt + JWT live here)**

```python
# backend/src/aura/api/security.py
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from passlib.context import CryptContext

from aura.config import get_settings
from aura.core.domain.user import User

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return _pwd.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return _pwd.verify(plain, hashed)


def create_token(user: User) -> str:
    s = get_settings()
    expire = datetime.now(timezone.utc) + timedelta(minutes=s.jwt_ttl_minutes)
    payload = {"sub": str(user.id), "username": user.username,
               "role": user.role.value, "exp": expire}
    return jwt.encode(payload, s.jwt_secret, algorithm=ALGORITHM)


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, get_settings().jwt_secret, algorithms=[ALGORITHM])
    except JWTError:
        return None
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/unit/test_authenticate.py -v`
Expected: 3 passed

- [ ] **Step 6: Commit**

```bash
git add backend/src/aura/core/services/authenticate.py backend/src/aura/api/security.py backend/tests/unit/test_authenticate.py
git commit -m "feat: add authentication use case with bcrypt and JWT adapter"
```

---

### Task 11: API — app, DI wiring, event hub, routers

**Files:**
- Create: `backend/src/aura/api/schemas/dto.py`, `backend/src/aura/api/ws/hub.py`, `backend/src/aura/api/deps.py`, `backend/src/aura/api/routers/auth.py`, `jobs.py`, `approvals.py`, `activity.py`, `backend/src/aura/api/main.py`, `backend/src/aura/data/seed.py`
- Test: `backend/tests/integration/test_api.py`

**Interfaces:**
- Consumes: everything above
- Produces: FastAPI `app`; endpoints `POST /api/auth/login`, `GET /api/auth/me`, `POST /api/jobs`, `GET /api/jobs`, `GET /api/jobs/{id}`, `GET /api/approvals`, `POST /api/approvals/{id}/approve`, `POST /api/approvals/{id}/reject`, `GET /api/activity`, `WS /ws/events`; `seed_admin()` creating user `bhavesh` / password `admin123` with role admin.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/integration/test_api.py
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from aura.api.deps import get_session
from aura.api.main import app
from aura.api.security import hash_password
from aura.data.engine import Base, make_engine
from aura.data.models.tables import UserRow


@pytest.fixture()
def client():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    session.add(UserRow(username="bhavesh", password_hash=hash_password("admin123"),
                        role="admin"))
    session.commit()

    app.dependency_overrides[get_session] = lambda: session
    yield TestClient(app)
    app.dependency_overrides.clear()


def _token(client):
    r = client.post("/api/auth/login", json={"username": "bhavesh", "password": "admin123"})
    assert r.status_code == 200
    return r.json()["access_token"]


def test_login_rejects_bad_password(client):
    r = client.post("/api/auth/login", json={"username": "bhavesh", "password": "wrong"})
    assert r.status_code == 401


def test_submit_job_returns_202_and_creates_job(client):
    headers = {"Authorization": f"Bearer {_token(client)}"}
    r = client.post("/api/jobs", json={"inputs": {"brief": "draft intro"}, "deal_id": None},
                    headers=headers)
    assert r.status_code == 202
    assert r.json()["status"] == "pending"

    listed = client.get("/api/jobs", headers=headers)
    assert listed.status_code == 200
    assert len(listed.json()) == 1


def test_jobs_require_auth(client):
    assert client.get("/api/jobs").status_code == 401


def test_approvals_list_is_empty_initially(client):
    headers = {"Authorization": f"Bearer {_token(client)}"}
    r = client.get("/api/approvals", headers=headers)
    assert r.status_code == 200
    assert r.json() == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/test_api.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'aura.api.main'`

- [ ] **Step 3: Write `schemas/dto.py`**

```python
# backend/src/aura/api/schemas/dto.py
from datetime import datetime

from pydantic import BaseModel


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class MeResponse(BaseModel):
    id: int
    username: str
    role: str


class SubmitJobRequest(BaseModel):
    inputs: dict
    deal_id: int | None = None


class JobResponse(BaseModel):
    id: int
    status: str
    inputs: dict
    result: dict | None
    deal_id: int | None
    created_at: datetime


class ApprovalResponse(BaseModel):
    id: int
    segment_id: int
    category: str
    proposed_action: dict
    status: str


class AuditResponse(BaseModel):
    id: int
    job_id: int | None
    actor: str
    action: str
    payload: dict
    created_at: datetime
```

- [ ] **Step 4: Write `ws/hub.py`**

```python
# backend/src/aura/api/ws/hub.py
import asyncio
from contextlib import suppress

from fastapi import WebSocket


class EventHub:
    """In-process fan-out. Satisfies core.ports.events.EventPublisher."""

    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._clients.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self._clients.discard(ws)

    def publish(self, event_type: str, payload: dict) -> None:
        """Thread-safe: callable from the worker thread."""
        message = {"type": event_type, "payload": payload}
        if self._loop is None:
            return
        with suppress(RuntimeError):
            asyncio.run_coroutine_threadsafe(self._broadcast(message), self._loop)

    async def _broadcast(self, message: dict) -> None:
        for ws in list(self._clients):
            try:
                await ws.send_json(message)
            except Exception:
                self.disconnect(ws)


hub = EventHub()
```

- [ ] **Step 5: Write `deps.py`**

```python
# backend/src/aura/api/deps.py
from typing import Generator

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from aura.api.security import decode_token
from aura.api.ws.hub import hub
from aura.core.domain.enums import Role
from aura.core.domain.user import User
from aura.data.engine import SessionLocal
from aura.data.repositories.sql import (SqlApprovalRepository, SqlAuditRepository,
                                        SqlJobRepository, SqlSegmentRepository,
                                        SqlUserRepository)

bearer = HTTPBearer(auto_error=False)


def get_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def get_jobs(s: Session = Depends(get_session)) -> SqlJobRepository:
    return SqlJobRepository(s)


def get_segments(s: Session = Depends(get_session)) -> SqlSegmentRepository:
    return SqlSegmentRepository(s)


def get_approvals(s: Session = Depends(get_session)) -> SqlApprovalRepository:
    return SqlApprovalRepository(s)


def get_audit(s: Session = Depends(get_session)) -> SqlAuditRepository:
    return SqlAuditRepository(s)


def get_users(s: Session = Depends(get_session)) -> SqlUserRepository:
    return SqlUserRepository(s)


def get_events():
    return hub


def current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    users: SqlUserRepository = Depends(get_users),
) -> User:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    claims = decode_token(creds.credentials)
    if claims is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")
    user = users.get(int(claims["sub"]))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown user")
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    if user.role is not Role.ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin role required")
    return user
```

- [ ] **Step 6: Write the routers**

```python
# backend/src/aura/api/routers/auth.py
from fastapi import APIRouter, Depends, HTTPException, status

from aura.api.deps import current_user, get_users
from aura.api.schemas.dto import LoginRequest, MeResponse, TokenResponse
from aura.api.security import create_token, verify_password
from aura.core.domain.user import User
from aura.core.services.authenticate import authenticate
from aura.data.repositories.sql import SqlUserRepository

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, users: SqlUserRepository = Depends(get_users)):
    user = authenticate(body.username, body.password, users, verify_password)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
    return TokenResponse(access_token=create_token(user))


@router.get("/me", response_model=MeResponse)
def me(user: User = Depends(current_user)):
    return MeResponse(id=user.id, username=user.username, role=user.role.value)
```

```python
# backend/src/aura/api/routers/jobs.py
from fastapi import APIRouter, Depends, HTTPException, status

from aura.api.deps import (current_user, get_audit, get_events, get_jobs,
                           get_segments)
from aura.api.schemas.dto import JobResponse, SubmitJobRequest
from aura.core.domain.user import User
from aura.core.services.submit_job import submit_job

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


def _to_response(job) -> JobResponse:
    return JobResponse(id=job.id, status=job.status.value, inputs=job.inputs,
                       result=job.result, deal_id=job.deal_id, created_at=job.created_at)


@router.post("", response_model=JobResponse, status_code=status.HTTP_202_ACCEPTED)
def create_job(body: SubmitJobRequest, user: User = Depends(current_user),
               jobs=Depends(get_jobs), segments=Depends(get_segments),
               audit=Depends(get_audit), events=Depends(get_events)):
    job = submit_job(inputs=body.inputs, deal_id=body.deal_id, actor=user.username,
                     jobs=jobs, segments=segments, audit=audit, events=events)
    return _to_response(job)


@router.get("", response_model=list[JobResponse])
def list_jobs(user: User = Depends(current_user), jobs=Depends(get_jobs)):
    return [_to_response(j) for j in jobs.list_recent()]


@router.get("/{job_id}", response_model=JobResponse)
def get_job(job_id: int, user: User = Depends(current_user), jobs=Depends(get_jobs)):
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    return _to_response(job)
```

```python
# backend/src/aura/api/routers/approvals.py
from fastapi import APIRouter, Depends, HTTPException, status

from aura.api.deps import (get_approvals, get_audit, get_events, get_jobs,
                           get_segments, require_admin)
from aura.api.schemas.dto import ApprovalResponse
from aura.core.domain.user import User
from aura.core.services.decide_approval import decide_approval

router = APIRouter(prefix="/api/approvals", tags=["approvals"])


def _to_response(a) -> ApprovalResponse:
    return ApprovalResponse(id=a.id, segment_id=a.segment_id, category=a.category.value,
                            proposed_action=a.proposed_action, status=a.status.value)


@router.get("", response_model=list[ApprovalResponse])
def list_pending(user: User = Depends(require_admin), approvals=Depends(get_approvals)):
    return [_to_response(a) for a in approvals.list_pending()]


def _decide(approval_id: int, approved: bool, user, jobs, segments, approvals, audit, events):
    try:
        decision = decide_approval(approval_id, approved, user.id, user.username,
                                   jobs, segments, approvals, audit, events)
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc))
    return _to_response(decision)


@router.post("/{approval_id}/approve", response_model=ApprovalResponse)
def approve(approval_id: int, user: User = Depends(require_admin), jobs=Depends(get_jobs),
            segments=Depends(get_segments), approvals=Depends(get_approvals),
            audit=Depends(get_audit), events=Depends(get_events)):
    return _decide(approval_id, True, user, jobs, segments, approvals, audit, events)


@router.post("/{approval_id}/reject", response_model=ApprovalResponse)
def reject(approval_id: int, user: User = Depends(require_admin), jobs=Depends(get_jobs),
           segments=Depends(get_segments), approvals=Depends(get_approvals),
           audit=Depends(get_audit), events=Depends(get_events)):
    return _decide(approval_id, False, user, jobs, segments, approvals, audit, events)
```

```python
# backend/src/aura/api/routers/activity.py
from fastapi import APIRouter, Depends

from aura.api.deps import current_user, get_audit
from aura.api.schemas.dto import AuditResponse
from aura.core.domain.user import User

router = APIRouter(prefix="/api/activity", tags=["activity"])


@router.get("", response_model=list[AuditResponse])
def list_activity(user: User = Depends(current_user), audit=Depends(get_audit)):
    return [AuditResponse(id=e.id, job_id=e.job_id, actor=e.actor, action=e.action,
                          payload=e.payload, created_at=e.created_at)
            for e in audit.list_recent()]
```

- [ ] **Step 7: Write `data/seed.py` and `api/main.py`**

```python
# backend/src/aura/data/seed.py
from sqlalchemy import select
from sqlalchemy.orm import Session

from aura.api.security import hash_password
from aura.data.engine import Base, SessionLocal, engine
from aura.data.models.tables import DealRow, UserRow


def seed() -> None:
    Base.metadata.create_all(engine)
    with SessionLocal() as s:  # type: Session
        if s.scalars(select(UserRow).where(UserRow.username == "bhavesh")).first() is None:
            s.add(UserRow(username="bhavesh", password_hash=hash_password("admin123"),
                          role="admin"))
        if s.scalars(select(DealRow)).first() is None:
            s.add_all([
                DealRow(external_id="D-001", name="Sunrise Infra",
                        stage="NDA signed", owner="bhavesh"),
                DealRow(external_id="D-002", name="Ravi Menon Ventures",
                        stage="Sourced", owner="bhavesh"),
            ])
        s.commit()
```

```python
# backend/src/aura/api/main.py
import asyncio

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from aura.api.routers import activity, approvals, auth, jobs
from aura.api.security import decode_token
from aura.api.ws.hub import hub
from aura.data.seed import seed

app = FastAPI(title="Yuki OS Portal API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(jobs.router)
app.include_router(approvals.router)
app.include_router(activity.router)


@app.on_event("startup")
def on_startup() -> None:
    seed()
    hub.bind_loop(asyncio.get_running_loop())


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.websocket("/ws/events")
async def events_socket(websocket: WebSocket, token: str = "") -> None:
    if decode_token(token) is None:
        await websocket.close(code=1008)
        return
    await hub.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        hub.disconnect(websocket)
```

- [ ] **Step 8: Run tests**

```bash
uv run pytest tests -v
uv run lint-imports --config .importlinter
```

Expected: all pass; contract KEPT.

- [ ] **Step 9: Verify the server boots**

```bash
uv run uvicorn aura.api.main:app --reload --port 8000
```

Expected: startup with no errors; `http://localhost:8000/docs` lists all endpoints. Stop with Ctrl-C.

- [ ] **Step 10: Commit**

```bash
git add backend/src/aura/api backend/src/aura/data/seed.py backend/tests/integration/test_api.py
git commit -m "feat: add FastAPI surface with auth, jobs, approvals, activity and event socket"
```

---

### Task 12: Worker — the segment runner loop

**Files:**
- Create: `backend/src/aura/worker/stub_orchestrator.py`, `backend/src/aura/worker/runner.py`
- Test: `backend/tests/integration/test_worker_loop.py`

**Interfaces:**
- Consumes: `run_segment` (Task 7), repositories (Task 9)
- Produces: `StubOrchestrator` (proposes `send_email` on the first segment, completes on the second); `run_once(session, orchestrator, events) -> bool`; `start_worker()` background thread.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/integration/test_worker_loop.py
from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import Session

from aura.core.domain.enums import ApprovalStatus, JobStatus, SegmentStatus
from aura.core.domain.job import Job
from aura.core.domain.segment import Segment
from aura.data.engine import Base, make_engine
from aura.data.repositories.sql import (SqlApprovalRepository, SqlAuditRepository,
                                        SqlJobRepository, SqlSegmentRepository)
from aura.worker.runner import run_once
from aura.worker.stub_orchestrator import StubOrchestrator


class NullEvents:
    def publish(self, event_type: str, payload: dict) -> None:
        pass


@pytest.fixture()
def session():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def test_worker_runs_queued_segment_and_stops_at_gate(session):
    jobs, segs = SqlJobRepository(session), SqlSegmentRepository(session)
    approvals = SqlApprovalRepository(session)
    job = jobs.add(Job(id=None, status=JobStatus.PENDING, inputs={"brief": "x"},
                       deal_id=None, result=None, created_at=datetime.now(timezone.utc)))
    segs.add(Segment(id=None, job_id=job.id, seq=1, status=SegmentStatus.QUEUED,
                     context_in={"brief": "x"}, context_out=None,
                     started_at=None, ended_at=None))

    did_work = run_once(session, StubOrchestrator(), NullEvents())

    assert did_work is True
    assert jobs.get(job.id).status is JobStatus.AWAITING_APPROVAL
    pending = approvals.list_pending()
    assert len(pending) == 1
    assert pending[0].status is ApprovalStatus.PENDING


def test_worker_returns_false_when_nothing_queued(session):
    assert run_once(session, StubOrchestrator(), NullEvents()) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/test_worker_loop.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'aura.worker.runner'`

- [ ] **Step 3: Write `stub_orchestrator.py`**

```python
# backend/src/aura/worker/stub_orchestrator.py
"""Deterministic stand-in for the CrewAI orchestrator (Plan 2 replaces this).

Segment 1 proposes an outbound email (exercising the gate); once the context
carries an approved draft, the next segment completes the job.
"""
from aura.core.domain.enums import ActionCategory
from aura.core.domain.segment import ProposedAction
from aura.core.ports.orchestrator import OrchestratorResult


class StubOrchestrator:
    def run(self, context_in: dict) -> OrchestratorResult:
        if context_in.get("draft"):
            return OrchestratorResult(completed=True,
                                      context_out={**context_in, "sent": True},
                                      proposed_action=None)

        brief = context_in.get("brief", "(no brief)")
        draft = f"Dear contact,\n\nRegarding: {brief}\n\nBest,\nOpulence"
        return OrchestratorResult(
            completed=False,
            context_out={**context_in, "draft": draft},
            proposed_action=ProposedAction(
                tool="send_email",
                category=ActionCategory.OUTBOUND,
                arguments={"body": draft},
                summary=f"Send outbound email: {brief}",
            ),
        )
```

- [ ] **Step 4: Write `runner.py`**

```python
# backend/src/aura/worker/runner.py
import threading
import time

from sqlalchemy.orm import Session

from aura.core.ports.events import EventPublisher
from aura.core.ports.orchestrator import Orchestrator
from aura.core.services.run_segment import run_segment
from aura.data.engine import SessionLocal
from aura.data.repositories.sql import (SqlApprovalRepository, SqlAuditRepository,
                                        SqlJobRepository, SqlSegmentRepository)

POLL_SECONDS = 2.0


def run_once(session: Session, orchestrator: Orchestrator, events: EventPublisher) -> bool:
    """Claim and run one queued segment. Returns True if work was done."""
    segments = SqlSegmentRepository(session)
    claimed = segments.claim_next_queued()
    if claimed is None:
        return False

    run_segment(
        segment_id=claimed.id,
        orchestrator=orchestrator,
        jobs=SqlJobRepository(session),
        segments=segments,
        approvals=SqlApprovalRepository(session),
        audit=SqlAuditRepository(session),
        events=events,
    )
    return True


def _loop(orchestrator: Orchestrator, events: EventPublisher, stop: threading.Event) -> None:
    while not stop.is_set():
        with SessionLocal() as session:
            try:
                did_work = run_once(session, orchestrator, events)
            except Exception:
                did_work = False
        if not did_work:
            stop.wait(POLL_SECONDS)


def start_worker(orchestrator: Orchestrator, events: EventPublisher) -> threading.Event:
    """Start the segment loop in a daemon thread. Returns its stop event."""
    stop = threading.Event()
    threading.Thread(target=_loop, args=(orchestrator, events, stop), daemon=True).start()
    return stop
```

- [ ] **Step 5: Start the worker from the API on startup**

Modify `backend/src/aura/api/main.py` — replace the `on_startup` function with:

```python
@app.on_event("startup")
def on_startup() -> None:
    seed()
    hub.bind_loop(asyncio.get_running_loop())
    app.state.worker_stop = start_worker(StubOrchestrator(), hub)
```

Add these imports at the top of `main.py`:

```python
from aura.worker.runner import start_worker
from aura.worker.stub_orchestrator import StubOrchestrator
```

- [ ] **Step 6: Run all tests**

```bash
uv run pytest tests -v
uv run lint-imports --config .importlinter
```

Expected: all pass; contract KEPT.

- [ ] **Step 7: Verify the full loop by hand**

```bash
uv run uvicorn aura.api.main:app --port 8000
```

In a second terminal:

```bash
TOKEN=$(curl -s -X POST localhost:8000/api/auth/login -H 'Content-Type: application/json' \
  -d '{"username":"bhavesh","password":"admin123"}' | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

curl -s -X POST localhost:8000/api/jobs -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"inputs":{"brief":"intro to D-002"}}'

sleep 3
curl -s localhost:8000/api/approvals -H "Authorization: Bearer $TOKEN"
curl -s -X POST localhost:8000/api/approvals/1/approve -H "Authorization: Bearer $TOKEN"
sleep 3
curl -s localhost:8000/api/jobs/1 -H "Authorization: Bearer $TOKEN"
```

Expected: the job reaches `awaiting_approval`, one approval is listed, and after approving, the job reaches `complete`.

- [ ] **Step 8: Commit**

```bash
git add backend/src/aura/worker backend/src/aura/api/main.py backend/tests/integration/test_worker_loop.py
git commit -m "feat: add segment worker loop with stub orchestrator"
```

---

## Self-Review

**Spec coverage:**

| ARCHITECTURE.md section       | Covered by            |
| ----------------------------- | --------------------- |
| §3 segmented execution        | Tasks 7, 8, 12        |
| §3 default-deny classification | Task 3               |
| §5 dependency rule, enforced  | Task 1 (`.importlinter`), re-verified in Tasks 5, 8, 9, 11, 12 |
| §6 backend structure          | Tasks 1, 9, 11, 12    |
| §8 data model (incl. SEGMENT) | Tasks 2, 9            |
| §8 append-only audit          | Task 5 (port), Task 9 (`SqlAuditRepository` has no update/delete) |
| §9 API never waits on inference | Task 11 (202 Accepted), Task 12 (worker thread) |
| §11 "repo not under version control" | Task 1, Step 1 |

**Deferred to later plans (deliberate, not gaps):** MCP layer and CrewAI orchestrator (Plan 2 — replaces `StubOrchestrator` behind the same port); Next.js portal (Plan 3); Alembic migrations (`Base.metadata.create_all` suffices until the schema changes in anger); `Deal` read endpoints (Plan 3, alongside the UI that consumes them).

**Type consistency:** `OrchestratorResult(completed, context_out, proposed_action)` is used identically in Tasks 5, 7, and 12. `ProposedAction(tool, category, arguments, summary)` is consistent across Tasks 2, 7, and 12. Repository method names match their protocols in Tasks 5, 9, and 12.

**Placeholder scan:** no TBDs; every code step carries runnable code.
