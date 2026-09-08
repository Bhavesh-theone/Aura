from aura.agents.factory import make_orchestrator
from aura.core.ports.orchestrator import Orchestrator


def test_factory_returns_something_satisfying_the_port():
    assert isinstance(make_orchestrator(), Orchestrator)


def test_factory_falls_back_to_stub_when_ollama_is_down():
    orchestrator = make_orchestrator(base_url="http://localhost:1")
    assert type(orchestrator).__name__ == "StubOrchestrator"
