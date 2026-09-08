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
