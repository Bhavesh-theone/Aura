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
