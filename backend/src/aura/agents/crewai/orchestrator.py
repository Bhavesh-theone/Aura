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
