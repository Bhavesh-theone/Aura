"""The deals MCP tools on the crew, behind gate_policy (F11.3 / G2.4)."""
import pytest

import aura.agents.crewai.crews as crews
from aura.agents.crewai.orchestrator import CrewOrchestrator
from aura.agents.crewai.tools import ToolGate, build_deal_tools, deals_server_functions
from aura.core.domain.enums import ActionCategory
from aura.mcp.identity import acting_username


class Spies:
    """Stand-ins for the MCP functions that record every time a body actually runs."""

    def __init__(self):
        self.calls = []

    def functions(self):
        def get_deal_status(deal_id: str) -> str:
            """Look up a deal."""
            self.calls.append(("get_deal_status", {"deal_id": deal_id}, acting_username()))
            return f"{deal_id}: ORIGINATED"

        def list_deals() -> str:
            """List deals."""
            self.calls.append(("list_deals", {}, acting_username()))
            return "D-1"

        def add_internal_note(deal_id: str, note: str) -> str:
            """Add a note."""
            self.calls.append(("add_internal_note", {"deal_id": deal_id}, acting_username()))
            return "noted"

        def send_email(to: str, subject: str, body: str) -> str:
            """Send an outbound email."""
            self.calls.append(("send_email", {"to": to}, acting_username()))
            return f"SENT to {to}"

        def wire_transfer(amount_inr: int) -> str:
            """Not in the gate policy at all."""
            self.calls.append(("wire_transfer", {}, acting_username()))
            return "wired"

        return {f.__name__: f for f in (get_deal_status, list_deals, add_internal_note,
                                        send_email, wire_transfer)}


def _tools(spies, gate=None, username="asha"):
    gate = gate or ToolGate("intro email")
    return gate, {t.name: t for t in build_deal_tools(gate, username, spies.functions())}


def test_send_emails_body_never_runs_and_the_attempt_is_recorded_instead():
    spies = Spies()
    gate, tools = _tools(spies)
    answer = tools["send_email"].run(to="ravi@example.com", subject="Hi", body="Dear Ravi")
    assert spies.calls == []  # the tool body did not run
    assert "NOT EXECUTED" in answer and "send_email" in answer
    (action,) = gate.proposals
    assert action.tool == "send_email" and action.category is ActionCategory.OUTBOUND
    assert action.arguments == {"to": "ravi@example.com", "subject": "Hi", "body": "Dear Ravi"}
    assert action.summary == "intro email"
    # calling it again, or in any other way, still never runs it
    tools["send_email"].run(to="x@y.z", subject="s", body="b")
    assert spies.calls == [] and len(gate.proposals) == 2


def test_ungated_tools_execute_as_the_acting_user():
    spies = Spies()
    gate, tools = _tools(spies, username="asha")
    assert tools["get_deal_status"].run(deal_id="D-1") == "D-1: ORIGINATED"
    assert tools["list_deals"].run() == "D-1"
    assert tools["add_internal_note"].run(deal_id="D-1", note="spoke") == "noted"
    assert [(name, user) for name, _, user in spies.calls] == [
        ("get_deal_status", "asha"), ("list_deals", "asha"), ("add_internal_note", "asha")]
    assert gate.proposals == []


def test_unmapped_tools_are_gated_by_default_deny():
    spies = Spies()
    gate, tools = _tools(spies)
    tools["wire_transfer"].run(amount_inr=10)
    assert spies.calls == [] and gate.proposals[0].category is ActionCategory.UNKNOWN


def test_an_ungated_tool_above_the_materiality_cap_is_gated_too():
    spies = Spies()
    gate, tools = _tools(spies, ToolGate("x", cap_inr=1_000))
    tools["wire_transfer"].run(amount_inr=5_000)
    assert spies.calls == [] and gate.proposals[0].materiality_inr == 5_000


def test_the_tools_carry_the_functions_signature_and_docstring():
    _, tools = _tools(Spies())
    assert tools["send_email"].description == "Send an outbound email."
    assert set(tools["send_email"].args_schema.model_fields) == {"to", "subject", "body"}
    assert set(tools["get_deal_status"].args_schema.model_fields) == {"deal_id"}


def test_the_real_deals_server_tools_are_the_ones_attached_by_default():
    assert set(deals_server_functions()) == {"get_deal_status", "list_deals",
                                             "add_internal_note", "send_email"}
    tools = build_deal_tools(ToolGate("x"), "asha")
    assert {t.name for t in tools} == set(deals_server_functions())


def test_the_real_send_email_body_is_unreachable_from_the_crew(monkeypatch):
    from aura.mcp.servers import deals_server
    ran = []
    monkeypatch.setattr(deals_server, "send_email", lambda to, subject, body: ran.append(to))
    gate = ToolGate("x")
    tools = {t.name: t for t in build_deal_tools(gate, "asha")}
    tools["send_email"].run(to="a@b.c", subject="s", body="b")
    assert ran == [] and len(gate.proposals) == 1


# ------------------------------------------------------------ through the orchestrator

class FakeCrew:
    """A crew whose 'agents' call the attached tools, as a model would."""

    def __init__(self, tools, script):
        self.tools, self.script = {t.name: t for t in tools}, script

    def kickoff(self, inputs):
        for name, args in self.script:
            self.tools[name].run(**args)
        return "Draft is ready."


def _orchestrator(monkeypatch, spies, script):
    monkeypatch.setattr(crews, "build_crew", lambda llm, tools=None: FakeCrew(tools, script))
    return CrewOrchestrator(tool_functions=spies.functions())


def test_a_gated_tool_call_makes_the_segment_propose_the_action_and_pause(monkeypatch):
    spies = Spies()
    orchestrator = _orchestrator(monkeypatch, spies, [
        ("get_deal_status", {"deal_id": "D-1"}),
        ("send_email", {"to": "ravi@example.com", "subject": "Hi", "body": "Dear Ravi"})])
    result = orchestrator._brief(None, {"brief": "Introduce us to Ravi"}, "asha")
    assert result.completed is False
    assert result.proposed_action.tool == "send_email"
    assert result.proposed_action.category is ActionCategory.OUTBOUND
    assert result.proposed_action.summary == "Introduce us to Ravi"
    assert result.context_out["approved_draft"] is True
    assert [c[0] for c in spies.calls] == ["get_deal_status"]  # the read ran, the send did not


def test_ungated_tool_calls_alone_let_the_job_complete(monkeypatch):
    spies = Spies()
    orchestrator = _orchestrator(monkeypatch, spies, [("list_deals", {})])
    result = orchestrator._brief(None, {"brief": "what deals do we have"}, "asha")
    assert result.completed is True and result.proposed_action is None
    assert [c[0] for c in spies.calls] == ["list_deals"]


def test_a_draft_email_job_never_sends_even_if_the_agent_tries(monkeypatch):
    spies = Spies()
    orchestrator = _orchestrator(monkeypatch, spies, [
        ("send_email", {"to": "x", "subject": "s", "body": "b"})])
    context = {"deal": {"name": "Sunrise", "stage": "ORIGINATED"},
               "party": {"id": 1, "display_name": "Ravi", "role": "buyer"}}
    result = orchestrator._draft_email(None, context, "asha")
    assert spies.calls == []
    assert result.proposed_action.tool == "draft_email"  # still only a draft for a human


def test_the_orchestrator_hands_the_acting_user_to_the_tools(monkeypatch):
    spies = Spies()
    orchestrator = _orchestrator(monkeypatch, spies, [("list_deals", {})])
    orchestrator._brief(None, {"brief": "x"}, "priya")
    assert spies.calls[0][2] == "priya"


def test_run_segment_turns_the_intercepted_call_into_a_task_and_handoff(monkeypatch):
    """The whole path: crew attempts send_email -> segment pauses with a handoff."""
    from tests.unit.test_run_segment_extras import World
    spies = Spies()
    inner = _orchestrator(monkeypatch, spies, [
        ("send_email", {"to": "ravi@example.com", "subject": "Hi", "body": "Dear Ravi"})])

    class Adapter:
        def run(self, context_in, run_context):
            return inner._brief(None, context_in, run_context.username)

    w = World({"brief": "Introduce us to Ravi"})
    w.run(Adapter())
    assert spies.calls == []
    (handoff,) = w.handoffs.open_ones()
    assert handoff.task_type == "send_email" and handoff.trigger.value == "policy_required"
    assert w.jobs.get(w.job.id).status.value == "awaiting_approval"
    assert w.segments.get(w.seg.id).status.value == "awaiting_approval"
    assert handoff.context_package["proposed_action"]["arguments"]["to"] == "ravi@example.com"