import pytest
from crewai import LLM

from aura.agents.crewai.orchestrator import CrewOrchestrator, parse_classification
from aura.agents.crewai.recording_llm import instrument_llm
from aura.agents.llm.recording import RunRecorder
from aura.core.ports.orchestrator import AgentRunLogError, RunContext
from tests.unit.fakes import FakeRunSink


class FakeAgent:
    role = "Drafter"


def _llm():
    return LLM(model="ollama/qwen3.5:4b", base_url="http://localhost:1")


def test_instrumented_llm_records_every_call(monkeypatch):
    sink = FakeRunSink()
    llm = _llm()
    monkeypatch.setattr(type(llm), "call", lambda self, messages, *a, **k: "a draft")
    instrument_llm(llm, RunRecorder(RunContext(1, 2, None, sink), "qwen3.5:4b", "digest"))

    assert llm.call([{"role": "user", "content": "write"}], from_agent=FakeAgent()) == "a draft"
    assert llm.call("plain string prompt") == "a draft"
    assert len(sink.runs) == 2
    first, second = sink.runs
    assert first.archetype == "Drafter" and first.prompt_template_id == "crew.drafter@v1"
    assert second.input_digest["messages"] == [{"role": "user", "content": "plain string prompt"}]
    assert second.prompt_template_id == "crew.unregistered"


def test_instrumented_llm_raises_instead_of_returning_unrecorded_output(monkeypatch):
    llm = _llm()
    monkeypatch.setattr(type(llm), "call", lambda self, messages, *a, **k: "secret")
    instrument_llm(llm, RunRecorder(RunContext(1, 2, None, FakeRunSink(fail=True)), "m", "v"))
    with pytest.raises(AgentRunLogError):
        llm.call("anything")


def test_classification_parsing_falls_back_to_keeping_the_class():
    assert parse_classification('{"doc_class": "spa", "confidence": 0.9, "rationale": "r"}',
                                "nda") == ("spa", 0.9, "r")
    assert parse_classification("no json here", "nda")[:2] == ("nda", 0.0)
    assert parse_classification('{"doc_class": "memo", "confidence": 0.9}', "nda")[:2] == (
        "nda", 0.0)
    assert parse_classification('{"doc_class": "spa", "confidence": 7}', "nda")[:2] == (
        "nda", 0.0)


def test_resumed_segment_completes_without_calling_a_model():
    result = CrewOrchestrator().run({"proposal_made": True, "capability": "draft_email"},
                                    RunContext(1, 2, None, FakeRunSink()))
    assert result.completed and "sent" not in result.context_out
