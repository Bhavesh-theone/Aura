from aura.agents.factory import make_orchestrator
from aura.core.ports.orchestrator import Orchestrator


def test_factory_returns_something_satisfying_the_port():
    assert isinstance(make_orchestrator(), Orchestrator)


def test_factory_falls_back_to_stub_when_ollama_is_down():
    orchestrator = make_orchestrator(base_url="http://localhost:1")
    assert type(orchestrator).__name__ == "StubOrchestrator"


def test_the_real_crew_gets_the_deals_mcp_tools_behind_the_gate(monkeypatch):
    from aura.agents import factory

    monkeypatch.setattr(factory, "ollama_available", lambda url: True)
    orchestrator = factory.make_orchestrator(base_url="http://localhost:1")
    assert type(orchestrator).__name__ == "CrewOrchestrator"
    gate, tools = orchestrator._crew_tools("a brief", "asha")
    assert {t.name for t in tools} == {"get_deal_status", "list_deals", "add_internal_note",
                                       "send_email"}
    tools_by_name = {t.name: t for t in tools}
    tools_by_name["send_email"].run(to="a@b.c", subject="s", body="b")
    assert [a.tool for a in gate.proposals] == ["send_email"]