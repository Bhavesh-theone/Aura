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
