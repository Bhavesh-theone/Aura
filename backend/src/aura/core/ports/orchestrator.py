from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from aura.core.domain.agent_run import AgentRun
from aura.core.domain.extraction import ExtractionProposal
from aura.core.domain.segment import ProposedAction


class AgentRunLogError(Exception):
    """An agent run could not be recorded, so its output must not be used."""


class BudgetExceeded(Exception):
    """A segment used up its model-call or wall-clock budget. Permanent: retrying the same
    segment would only spend the budget again."""


class TransientModelError(Exception):
    """The model could not be reached or answered with a temporary error. Adapters raise
    (or wrap in) this so the worker retries the segment instead of failing it."""


@runtime_checkable
class AgentRunSink(Protocol):
    def record(self, run: AgentRun) -> AgentRun:
        """Persist the run durably or raise AgentRunLogError."""
        ...


@dataclass
class RunContext:
    """Who a model call is for, and where its lineage row goes."""
    job_id: int | None
    deal_id: int | None
    task_id: int | None
    runs: AgentRunSink
    username: str | None = None
    segment_id: int | None = None
    # Prepended to every run's archetype ('eval:' for golden-set runs).
    archetype_prefix: str = ""
    # Recorded in each run's input_digest (the context's prompt-injection screening).
    notes: dict | None = None


@dataclass
class OrchestratorResult:
    """Outcome of running one segment.

    completed=True  -> job is finished; proposed_action is None.
    completed=False -> an action needs approval; proposed_action is set.
    """
    completed: bool
    context_out: dict
    proposed_action: ProposedAction | None
    # Set by the extract_financials capability: what was read from a document.
    extraction: ExtractionProposal | None = None


@runtime_checkable
class Orchestrator(Protocol):
    def run(self, context_in: dict, run_context: RunContext) -> OrchestratorResult: ...
