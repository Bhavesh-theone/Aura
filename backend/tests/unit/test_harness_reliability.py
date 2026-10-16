"""Retry policy, per-call model retries, segment budgets and per-segment orchestrator choice."""
from datetime import datetime, timedelta, timezone

import pytest

from aura.agents.factory import OrchestratorSelector
from aura.agents.llm.recording import RunRecorder
from aura.core.domain.enums import JobStatus, SegmentStatus
from aura.core.domain.errors import RuleViolation
from aura.core.policy.retry_policy import RetryPolicy, is_transient
from aura.core.ports.orchestrator import (AgentRunLogError, BudgetExceeded, RunContext,
                                          TransientModelError)
from aura.core.services.segment_reliability import (handle_segment_failure, next_utc_day,
                                                    recover_stale_segments, retry_job)
from aura.core.domain.enums import Role
from aura.core.domain.errors import Conflict
from tests.unit.fakes import FakeRunSink
from tests.unit.test_run_segment import World

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)


class APIConnectionError(Exception):
    """Named like litellm's, which core cannot import."""


def test_transient_and_permanent_errors_are_told_apart():
    assert is_transient(ConnectionRefusedError("[Errno 111] Connection refused"))
    assert is_transient(TimeoutError("read timed out"))
    assert is_transient(APIConnectionError("OllamaException"))
    assert is_transient(TransientModelError("down"))
    wrapped = RuntimeError("crew failed")
    wrapped.__cause__ = ConnectionError("refused")
    assert is_transient(wrapped)
    for exc in (ValueError("bad json"), RuleViolation("no"), AgentRunLogError("x"),
                BudgetExceeded("over"), RuntimeError("model fell over")):
        assert not is_transient(exc)


def test_backoff_doubles_per_attempt():
    policy = RetryPolicy(max_attempts=3, base_backoff_seconds=10)
    assert [policy.backoff(n).total_seconds() for n in (1, 2, 3)] == [10, 20, 40]
    assert policy.can_retry(2) and not policy.can_retry(3)
    assert next_utc_day(NOW) == datetime(2026, 10, 8, tzinfo=timezone.utc)


# ------------------------------------------------------------------ segment failures

def _claimed(world: World, attempts: int) -> World:
    seg = world.segments.get(world.seg.id)
    seg.status, seg.attempts = SegmentStatus.RUNNING, attempts
    return world


def test_a_transient_failure_requeues_with_backoff_then_dead_letters():
    w = _claimed(World(deal_id=4), attempts=1)
    policy = RetryPolicy(max_attempts=2, base_backoff_seconds=10)
    job, seg = w.jobs.get(w.job.id), w.segments.get(w.seg.id)
    assert handle_segment_failure(seg, job, ConnectionRefusedError("refused"), policy,
                                  w.segments, w.jobs, w.audit, w.events, NOW) == "retry"
    assert seg.status is SegmentStatus.QUEUED and seg.not_before == NOW + timedelta(seconds=10)
    assert job.status is JobStatus.PENDING and "refused" in seg.last_error
    assert w.audit.entries[-1].action == "segment_retry_scheduled"
    assert w.audit.entries[-1].deal_id == 4

    seg.status, seg.attempts = SegmentStatus.RUNNING, 2
    assert handle_segment_failure(seg, job, ConnectionRefusedError("refused"), policy,
                                  w.segments, w.jobs, w.audit, w.events, NOW) == "dead_letter"
    assert seg.status is SegmentStatus.DEAD_LETTER and job.status is JobStatus.FAILED
    assert w.audit.entries[-1].action == "segment_dead_lettered"
    assert ("segment_dead_lettered", {"job_id": job.id, "deal_id": 4,
                                      "segment_id": seg.id}) in w.events.published


def test_a_permanent_failure_fails_at_once_and_says_why():
    w = _claimed(World(), attempts=1)
    job, seg = w.jobs.get(w.job.id), w.segments.get(w.seg.id)
    assert handle_segment_failure(seg, job, BudgetExceeded("too many calls"), RetryPolicy(),
                                  w.segments, w.jobs, w.audit, w.events, NOW) == "failed"
    assert seg.status is SegmentStatus.FAILED and job.status is JobStatus.FAILED
    assert seg.last_error == "BudgetExceeded: too many calls"
    entry = w.audit.entries[-1]
    assert entry.action == "segment_failed" and entry.payload["reason"] == "budget_exceeded"


def test_an_orphaned_running_segment_is_recovered_or_dead_lettered():
    policy = RetryPolicy(max_attempts=2, lease_seconds=60)
    w = _claimed(World(), attempts=1)
    seg = w.segments.get(w.seg.id)
    seg.claimed_at = NOW - timedelta(seconds=30)  # still within its lease
    assert recover_stale_segments(w.segments, w.jobs, w.audit, w.events, policy, NOW) == 0
    seg.claimed_at = NOW - timedelta(seconds=61)
    assert recover_stale_segments(w.segments, w.jobs, w.audit, w.events, policy, NOW) == 1
    assert seg.status is SegmentStatus.QUEUED and seg.claimed_by is None
    assert w.audit.entries[-1].action == "segment_recovered"

    seg.status, seg.attempts, seg.claimed_at = SegmentStatus.RUNNING, 2, NOW - timedelta(hours=1)
    recover_stale_segments(w.segments, w.jobs, w.audit, w.events, policy, NOW)
    assert seg.status is SegmentStatus.DEAD_LETTER
    assert w.jobs.get(w.job.id).status is JobStatus.FAILED
    assert w.audit.entries[-1].payload["reason"] == "lease_expired"


def test_a_person_can_retry_a_dead_lettered_job_once():
    w = World()
    seg = w.segments.get(w.seg.id)
    seg.status, seg.attempts, seg.last_error = SegmentStatus.DEAD_LETTER, 3, "refused"
    with pytest.raises(Exception):  # compliance does not run agent jobs
        retry_job(w.job.id, "priya", Role.COMPLIANCE, w.jobs, w.segments, w.audit, w.events)
    retry_job(w.job.id, "asha", Role.ANALYST, w.jobs, w.segments, w.audit, w.events, NOW)
    assert seg.status is SegmentStatus.QUEUED and seg.attempts == 0
    assert w.jobs.get(w.job.id).status is JobStatus.PENDING
    assert w.audit.entries[-1].action == "segment_retried"
    assert w.audit.entries[-1].payload["previous_error"] == "refused"
    with pytest.raises(Conflict):
        retry_job(w.job.id, "asha", Role.ANALYST, w.jobs, w.segments, w.audit, w.events)


# ------------------------------------------------------------------ model calls

def _recorder(sink, **kw):
    sleeps = []
    kw.setdefault("sleep", sleeps.append)
    rec = RunRecorder(RunContext(1, 2, None, sink, segment_id=7), "m", "v", **kw)
    return rec, sleeps


def test_a_transient_model_error_is_retried_and_every_attempt_is_on_record():
    sink = FakeRunSink()
    rec, sleeps = _recorder(sink, max_retries=2, retry_backoff_seconds=1.0)
    answers = iter([ConnectionRefusedError("refused"), TimeoutError("timed out"), "ok"])

    def call():
        answer = next(answers)
        if isinstance(answer, Exception):
            raise answer
        return answer

    assert rec.traced(call, archetype="a", template_id="t",
                      messages=[{"role": "user", "content": "x"}]) == "ok"
    assert [r.output for r in sink.runs] == [
        {"error": "ConnectionRefusedError: refused"}, {"error": "TimeoutError: timed out"},
        {"text": "ok"}]
    assert sleeps == [1.0, 2.0] and {r.segment_id for r in sink.runs} == {7}


def test_a_permanent_model_error_is_not_retried():
    sink = FakeRunSink()
    rec, sleeps = _recorder(sink, max_retries=2)

    def call():
        raise ValueError("bad request")

    with pytest.raises(ValueError):
        rec.traced(call, archetype="a", template_id="t", messages=[])
    assert len(sink.runs) == 1 and sleeps == []


def test_the_segment_call_budget_stops_the_next_call():
    sink = FakeRunSink()
    rec, _ = _recorder(sink, max_calls=2)
    for _ in range(2):
        rec.traced(lambda: "fine", archetype="a", template_id="t", messages=[])
    with pytest.raises(BudgetExceeded, match="max_llm_calls_per_segment"):
        rec.traced(lambda: "one too many", archetype="a", template_id="t", messages=[])
    assert len(sink.runs) == 2  # the refused call never ran


def test_the_segment_time_budget_stops_the_next_call():
    rec, _ = _recorder(FakeRunSink(), max_seconds=0)
    rec._started -= 1
    with pytest.raises(BudgetExceeded, match="max_segment_seconds"):
        rec.traced(lambda: "late", archetype="a", template_id="t", messages=[])


# ------------------------------------------------------------------ orchestrator choice

class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_the_orchestrator_is_chosen_per_segment_with_a_cached_health_check():
    checks, up, clock = [], {"value": True}, Clock()

    def available(url):
        checks.append(url)
        return up["value"]

    selector = OrchestratorSelector(base_url="http://ollama", ttl_seconds=30,
                                    available=available, crew_factory=lambda: "crew",
                                    stub_factory=lambda: "stub", clock=clock)
    first = selector.select()
    assert first.orchestrator == "crew" and first.fallback_reason is None
    up["value"] = False
    assert selector.select().orchestrator == "crew" and len(checks) == 1  # cached
    clock.t = 31
    down = selector.select()
    assert down.orchestrator == "stub" and "unreachable" in down.fallback_reason
    up["value"] = True
    selector.invalidate()
    assert selector.select().orchestrator == "crew" and len(checks) == 3


def test_a_crew_that_cannot_start_falls_back_too():
    def broken():
        raise ImportError("no crewai")

    selector = OrchestratorSelector(available=lambda url: True, crew_factory=broken,
                                    stub_factory=lambda: "stub")
    chosen = selector.select()
    assert chosen.orchestrator == "stub" and "could not start" in chosen.fallback_reason
