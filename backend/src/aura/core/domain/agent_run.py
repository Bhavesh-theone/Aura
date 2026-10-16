from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class AgentRun:
    """One model inference (SOSPE C6). Local inference costs nothing but the column exists."""
    id: int | None
    job_id: int | None
    deal_id: int | None
    task_id: int | None
    archetype: str
    model_id: str
    model_version: str
    prompt_template_id: str
    prompt_hash: str
    input_digest: dict
    output: dict
    confidence: float | None
    tokens_in: int
    tokens_out: int
    cost_inr: float
    latency_ms: int
    started_at: datetime
    completed_at: datetime
    tool_calls: list = field(default_factory=list)
    # The segment the run belonged to (lineage even before a task exists).
    segment_id: int | None = None
    # The llm.call span the run was recorded under (migration 0012).
    trace_id: str | None = None
    span_id: str | None = None
    # A deal-intake extraction call (archetype intake_extractor) made before the deal
    # exists: private to the intake's creator until the intake is confirmed.
    intake_id: int | None = None
