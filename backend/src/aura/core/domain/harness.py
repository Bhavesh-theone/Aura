"""Evaluation, autonomy, notes and trace records (migration 0012)."""
from dataclasses import dataclass, field
from datetime import datetime

EVAL_CAPABILITIES = ("classify_document", "extract_financials", "draft_email")

# Autonomy levels (SOSPE 9.6, adapted). 2: a confident result may complete without a
# handoff. 1: every result goes to a person. 0: the capability is switched off.
LEVEL_AUTONOMOUS, LEVEL_SUPERVISED, LEVEL_DISABLED = 2, 1, 0


@dataclass
class EvalCaseResult:
    id: int | None
    eval_run_id: int | None
    case_id: str
    passed: bool
    score: float
    confidence: float | None
    expected: dict
    actual: dict
    detail: dict = field(default_factory=dict)
    agent_run_id: int | None = None
    latency_ms: int = 0
    error: str | None = None


@dataclass
class EvalRun:
    id: int | None
    capability: str
    orchestrator: str
    model_id: str
    golden_sha256: str
    n_cases: int
    score: float
    threshold: float
    passed: bool
    metrics: dict
    started_at: datetime
    completed_at: datetime
    created_by: str = "system"
    cases: list[EvalCaseResult] = field(default_factory=list)


@dataclass
class CapabilityAutonomy:
    capability: str
    level: int = LEVEL_AUTONOMOUS
    pinned_model: str | None = None
    demoted_at: datetime | None = None
    reason: str | None = None
    updated_by: str | None = None
    updated_at: datetime | None = None


@dataclass
class DealNote:
    id: int | None
    deal_id: int
    body: str
    author: str
    source: str
    created_at: datetime
    job_id: int | None = None


@dataclass
class TraceSpanRecord:
    trace_id: str
    span_id: str
    parent_span_id: str | None
    name: str
    start: datetime
    end: datetime | None
    attributes: dict
    status: str
    deal_id: int | None = None
