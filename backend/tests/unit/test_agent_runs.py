import hashlib
import json

import pytest

from aura.agents.llm.recording import RunRecorder, prompt_hash
from aura.core.domain.enums import ActionCategory, DocClass
from aura.core.ports.orchestrator import AgentRunLogError, RunContext
from aura.worker.stub_orchestrator import StubOrchestrator, guess_class
from tests.unit.fakes import FakeRunSink


def _ctx(sink=None):
    return RunContext(job_id=3, deal_id=9, task_id=None, runs=sink or FakeRunSink())


def test_prompt_hash_is_sha256_of_the_canonical_messages():
    messages = [{"role": "user", "content": "hi"}]
    expected = hashlib.sha256(json.dumps(messages, sort_keys=True,
                                         separators=(",", ":")).encode()).hexdigest()
    assert prompt_hash(messages) == expected


def test_traced_call_records_before_returning_output():
    sink = FakeRunSink()
    rec = RunRecorder(_ctx(sink), "qwen3.5:4b", "abc123")
    usage = iter([(0, 0), (12, 5)])
    out = rec.traced(lambda: '{"confidence": 0.8, "tool": "send_email", "arguments": {}}',
                     archetype="Drafter", template_id="crew.drafter@v1",
                     messages=[{"role": "user", "content": "write"}], usage=lambda: next(usage))
    (run,) = sink.runs
    assert out.startswith("{") and run.model_id == "qwen3.5:4b"
    assert run.model_version == "abc123" and run.archetype == "Drafter"
    assert run.prompt_template_id == "crew.drafter@v1"
    assert run.prompt_hash == prompt_hash([{"role": "user", "content": "write"}])
    assert run.input_digest["messages"] == [{"role": "user", "content": "write"}]
    assert (run.tokens_in, run.tokens_out, run.cost_inr) == (12, 5, 0.0)
    assert run.confidence == 0.8 and run.tool_calls[0]["tool"] == "send_email"
    assert run.job_id == 3 and run.deal_id == 9 and run.latency_ms >= 0


def test_failure_to_record_blocks_the_output():
    rec = RunRecorder(_ctx(FakeRunSink(fail=True)), "m", "v")
    with pytest.raises(AgentRunLogError):
        rec.traced(lambda: "secret model output", archetype="a", template_id="t",
                   messages=[{"role": "user", "content": "x"}])


def test_a_failed_model_call_is_recorded_and_the_error_propagates():
    sink = FakeRunSink()
    rec = RunRecorder(_ctx(sink), "m", "v")

    def boom():
        raise TimeoutError("ollama gone")

    with pytest.raises(TimeoutError):
        rec.traced(boom, archetype="a", template_id="t",
                   messages=[{"role": "user", "content": "x"}])
    assert sink.runs[0].output == {"error": "TimeoutError: ollama gone"}


def test_stub_runs_write_a_row_with_model_id_stub():
    sink = FakeRunSink()
    result = StubOrchestrator().run({"brief": "hello"}, _ctx(sink))
    assert result.proposed_action.tool == "send_email"
    (run,) = sink.runs
    assert run.model_id == "stub" and run.archetype == "stub"
    assert run.prompt_template_id == "stub.brief.v1"
    assert run.tool_calls[0]["tool"] == "send_email"


def test_stub_output_is_withheld_when_the_row_cannot_be_written():
    with pytest.raises(AgentRunLogError):
        StubOrchestrator().run({"brief": "hello"}, _ctx(FakeRunSink(fail=True)))


def test_stub_resume_after_decision_completes_without_inference():
    sink = FakeRunSink()
    result = StubOrchestrator().run({"proposal_made": True}, _ctx(sink))
    assert result.completed and sink.runs == []


def test_stub_classifies_from_the_filename():
    assert guess_class("Acme_TermSheet_v3.pdf", "nda") == ("term_sheet", 0.9)
    assert guess_class("scan0001.pdf", "nda") == ("nda", 0.3)
    ctx = {"capability": "classify_document",
           "document": {"id": 4, "filename": "board resolution.docx",
                        "current_class": "nda", "excerpt": ""}}
    result = StubOrchestrator().run(ctx, _ctx())
    action = result.proposed_action
    assert action.tool == "classify_document"
    assert action.arguments["proposed_class"] == DocClass.BOARD_RESOLUTION.value
    assert result.context_out["proposal_made"] is True


def test_stub_email_draft_is_always_a_gated_outbound_proposal():
    ctx = {"capability": "draft_email", "brief": "Introduce us.",
           "deal": {"id": 1, "name": "Sunrise Infra", "stage": "QUALIFIED"},
           "party": {"id": 2, "display_name": "Acme Capital", "role": "lender"}}
    result = StubOrchestrator().run(ctx, _ctx())
    action = result.proposed_action
    assert action.tool == "draft_email" and action.category is ActionCategory.OUTBOUND
    assert "Acme Capital" in action.arguments["body"]
    assert "sent" not in result.context_out
