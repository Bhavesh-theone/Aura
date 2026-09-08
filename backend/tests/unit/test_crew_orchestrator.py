from aura.agents.crewai.orchestrator import CrewOrchestrator, decide_action
from aura.core.domain.enums import ActionCategory
from aura.core.ports.orchestrator import Orchestrator


def test_crew_orchestrator_satisfies_the_port():
    assert isinstance(CrewOrchestrator(), Orchestrator)


def test_decide_action_extracts_a_gated_tool_call():
    output = 'I will send this. ```json{"tool": "send_email", "arguments": {"to": "a@b.com"}}```'
    action = decide_action(output, {"brief": "intro"})
    assert action is not None
    assert action.tool == "send_email"
    assert action.category is ActionCategory.OUTBOUND


def test_decide_action_returns_none_for_ungated_tool():
    output = '{"tool": "get_deal_status", "arguments": {"deal_id": "D-001"}}'
    assert decide_action(output, {}) is None


def test_unmapped_tool_is_treated_as_gated():
    output = '{"tool": "wire_transfer", "arguments": {}}'
    action = decide_action(output, {})
    assert action is not None
    assert action.category is ActionCategory.UNKNOWN


def test_no_tool_call_means_no_action():
    assert decide_action("Here is a draft with no tool call.", {}) is None
