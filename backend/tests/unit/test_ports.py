from aura.core.ports.orchestrator import Orchestrator, OrchestratorResult


class StubOrchestrator:
    def run(self, context_in: dict, run_context) -> OrchestratorResult:
        return OrchestratorResult(completed=True, context_out={"ok": True}, proposed_action=None)


def test_stub_satisfies_orchestrator_protocol():
    assert isinstance(StubOrchestrator(), Orchestrator)


def test_orchestrator_result_carries_no_action_when_complete():
    result = StubOrchestrator().run({}, None)
    assert result.completed is True
    assert result.proposed_action is None
