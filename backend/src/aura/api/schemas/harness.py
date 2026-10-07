from datetime import datetime

from pydantic import BaseModel


class EvalCaseOut(BaseModel):
    case_id: str
    passed: bool
    score: float
    confidence: float | None
    expected: dict
    actual: dict
    detail: dict
    agent_run_id: int | None
    latency_ms: int
    error: str | None


class EvalRunOut(BaseModel):
    id: int
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
    created_by: str


class EvalRunDetailOut(EvalRunOut):
    cases: list[EvalCaseOut]


class OverrideRateOut(BaseModel):
    capability: str
    decisions: int
    overrides: int
    rate: float | None
    window_days: int


class AutonomyOut(BaseModel):
    capability: str
    level: int
    pinned_model: str | None
    demoted_at: datetime | None
    reason: str | None
    updated_by: str | None
    updated_at: datetime | None


class PromptTemplateOut(BaseModel):
    template_id: str
    version: int
    ref: str
    role: str
    sha256: str
    active: bool
    path: str


class TraceSpanOut(BaseModel):
    trace_id: str
    span_id: str
    parent_span_id: str | None
    name: str
    start: datetime
    end: datetime | None
    duration_ms: float | None
    attributes: dict
    status: str


class TraceOut(BaseModel):
    trace_id: str
    spans: list[TraceSpanOut]


class NoteOut(BaseModel):
    id: int
    deal_id: int
    body: str
    author: str
    source: str
    job_id: int | None
    created_at: datetime


class LatestEvalOut(BaseModel):
    capability: str
    eval_run_id: int
    orchestrator: str
    model_id: str
    score: float
    threshold: float
    passed: bool
    completed_at: datetime


class AutonomyLevelOut(BaseModel):
    capability: str
    level: int
    reason: str | None
    demoted_at: datetime | None


class EvaluationMetricsOut(BaseModel):
    latest_runs: list[LatestEvalOut]
    override_rate: list[OverrideRateOut]
    autonomy: list[AutonomyLevelOut]


class SecurityMetricsOut(BaseModel):
    injection_suspected: int
    untrusted_content_handoffs: int
