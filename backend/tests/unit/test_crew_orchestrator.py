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


def test_the_email_draft_is_the_drafters_output_not_the_reviewers_critique():
    from types import SimpleNamespace as NS

    from aura.agents.crewai.orchestrator import split_subject, task_texts
    out = NS(tasks_output=[NS(raw="facts"), NS(raw="Subject: Working capital\n\nDear team,\nHi"),
                           NS(raw="1. Capitalise the name.")])
    assert task_texts(out, 1).startswith("Subject:")
    assert task_texts(out, 5) == "" and task_texts(object(), 1) == ""
    assert split_subject(task_texts(out, 1), "Regarding X") == ("Working capital",
                                                                "Dear team,\nHi")
    assert split_subject("**Subject:** Hello\nBody", "d") == ("Hello", "Body")
    assert split_subject("Dear team", "Regarding X") == ("Regarding X", "Dear team")
