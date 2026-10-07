"""Reliability and state (agentic-harness gaps, categories 1, 3, 4, 7, 8 and 12) against a real
database: atomic claims, recovery, retries and dead letters, budgets, fallback, the handoff
resolve race and idempotent submission."""
import threading
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from aura.agents.factory import OrchestratorSelector
from aura.config import get_settings
from aura.core.domain.enums import (ActionCategory, AssignmentMode, HandoffDirection,
                                    HandoffStatus, HandoffTrigger, JobStatus, Role,
                                    SegmentStatus)

from aura.core.domain.errors import Conflict
from aura.core.domain.job import Job
from aura.core.domain.segment import ProposedAction, Segment
from aura.core.policy.handoff_policy import build_gate_package
from aura.core.policy.retry_policy import RetryPolicy
from aura.core.services.handoffs import create_handoff, resolve_handoff
from aura.data.engine import Base, make_engine
from aura.data.repositories.sql import (SqlAuditRepository, SqlHandoffRepository,
                                        SqlJobRepository, SqlSegmentRepository,
                                        SqlTaskRepository)
from aura.data.repositories.sql_deals import SqlDocumentRepository
from aura.data.walls import SYSTEM
from aura.worker.runner import run_once, sweep_stale_segments
from aura.worker.stub_orchestrator import StubOrchestrator
from tests.integration.helpers import DIRECTIVE, NullEvents, make_deal, run_worker, submit


class Recorder:
    def __init__(self):
        self.published = []

    def publish(self, event_type, payload):
        self.published.append((event_type, payload))


class Refused:
    """An orchestrator whose model is not answering."""

    def run(self, context_in, run_context):
        raise ConnectionRefusedError("[WinError 10061] connection refused by ollama")


class Broken:
    def run(self, context_in, run_context):
        raise ValueError("the model's answer failed validation")


def _segment(api, job_id):
    return api.session.execute(text(
        "SELECT status, attempts, last_error, not_before, claimed_by FROM segments "
        "WHERE job_id = :j ORDER BY seq DESC LIMIT 1"), {"j": job_id}).one()


def _actions(api, action):
    return api.session.execute(text("SELECT payload FROM audit_entries WHERE action = :a "
                                    "ORDER BY id"), {"a": action}).scalars().all()


@pytest.fixture()
def fast_retries(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "segment_backoff_seconds", 0.0)
    monkeypatch.setattr(s, "segment_max_attempts", 3)
    return s


# ------------------------------------------------------------------ atomic claim (cat 8)

@pytest.fixture()
def file_engine(tmp_path):
    engine = make_engine(f"sqlite:///{(tmp_path / 'race.db').as_posix()}")
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


def _queue(session, n):
    jobs, segs = SqlJobRepository(session, SYSTEM), SqlSegmentRepository(session)
    ids = []
    for i in range(n):
        job = jobs.add(Job(id=None, status=JobStatus.PENDING, inputs={"i": i}, deal_id=None,
                           result=None, created_at=datetime.now(timezone.utc)))
        ids.append(segs.add(Segment(id=None, job_id=job.id, seq=1,
                                    status=SegmentStatus.QUEUED, context_in={})).id)
    session.commit()
    return ids


def test_two_concurrent_claimers_never_get_the_same_segment(file_engine):
    with Session(file_engine) as s:
        queued = _queue(s, 30)
    got: dict[str, list[int]] = {"a": [], "b": []}
    start = threading.Barrier(2)

    def claimer(name):
        with Session(file_engine) as s:
            segs = SqlSegmentRepository(s)
            start.wait()
            while True:
                s.commit()
                seg = segs.claim_next_queued(name)
                s.commit()
                if seg is None:
                    return
                got[name].append(seg.id)

    threads = [threading.Thread(target=claimer, args=(n,)) for n in got]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert not set(got["a"]) & set(got["b"])
    assert sorted(got["a"] + got["b"]) == queued
    with Session(file_engine) as s:
        rows = s.execute(text("SELECT status, attempts, claimed_by FROM segments")).all()
    assert {(r.status, r.attempts) for r in rows} == {("running", 1)}
    assert {r.claimed_by for r in rows} <= {"a", "b"}


def test_a_segment_waits_for_its_not_before(file_engine):
    with Session(file_engine) as s:
        (seg_id,) = _queue(s, 1)
        later = datetime.now(timezone.utc) + timedelta(minutes=5)
        s.execute(text("UPDATE segments SET not_before = :t WHERE id = :i"),
                  {"t": later.replace(tzinfo=None).isoformat(sep=" "), "i": seg_id})
        s.commit()
        segs = SqlSegmentRepository(s)
        assert segs.claim_next_queued("w") is None
        assert segs.claim_next_queued("w", later + timedelta(seconds=1)).id == seg_id


# ------------------------------------------------------------------ retries, dead letters

def test_a_model_that_stays_down_is_retried_then_dead_lettered(api, fast_retries):
    deal = make_deal(api)
    job = submit(api, {"brief": "intro"}, deal_id=deal)
    events = Recorder()
    for _ in range(3):
        assert run_once(api.session, Refused(), events) is True
    assert run_once(api.session, Refused(), events) is False  # nothing left to claim

    status, attempts, last_error, _, _ = _segment(api, job["id"])
    assert (status, attempts) == ("dead_letter", 3)
    assert "ConnectionRefusedError" in last_error
    assert api.call("GET", f"/api/jobs/{job['id']}").json()["status"] == "failed"
    assert len(_actions(api, "segment_retry_scheduled")) == 2
    (dead,) = _actions(api, "segment_dead_lettered")
    assert '"attempts": 3' in dead
    assert ("segment_dead_lettered", {"job_id": job["id"], "deal_id": deal,
                                      "segment_id": 1}) in events.published

    listed = api.call("GET", "/api/jobs/dead-letter").json()
    assert [(d["job"]["id"], d["status"], d["attempts"]) for d in listed] == [
        (job["id"], "dead_letter", 3)]
    assert api.call("GET", "/api/jobs/dead-letter", user="priya").status_code == 403
    # off the wall: asha cannot see bhavesh's deal, so not its dead letters either
    assert api.call("GET", "/api/jobs/dead-letter", user="asha").json() == []
    assert api.call("POST", f"/api/jobs/{job['id']}/retry", user="asha").status_code == 404

    m = api.call("GET", "/api/metrics").json()["reliability"]
    assert m["dead_lettered_segments"] == 1 and m["retried_segments"] == 2

    r = api.call("POST", f"/api/jobs/{job['id']}/retry")
    assert r.status_code == 202 and r.json()["status"] == "pending"
    assert _segment(api, job["id"])[:2] == ("queued", 0)
    assert len(_actions(api, "segment_retried")) == 1
    assert api.call("POST", f"/api/jobs/{job['id']}/retry").status_code == 409
    run_worker(api)  # the model is back: the job carries on to its gate
    assert api.call("GET", f"/api/jobs/{job['id']}").json()["status"] == "awaiting_approval"
    assert api.call("GET", "/api/jobs/dead-letter").json() == []


def test_a_permanent_failure_is_not_retried(api, fast_retries):
    job = submit(api, {"brief": "intro"})
    assert run_once(api.session, Broken(), NullEvents()) is True
    assert run_once(api.session, Broken(), NullEvents()) is False
    status, attempts, last_error, _, _ = _segment(api, job["id"])
    assert (status, attempts) == ("failed", 1) and "failed validation" in last_error
    assert _actions(api, "segment_retry_scheduled") == []
    # a failed job can be retried by hand as well
    assert api.call("POST", f"/api/jobs/{job['id']}/retry").status_code == 202


def test_an_orphaned_running_segment_is_recovered_at_the_next_sweep(api):
    job = submit(api, {"brief": "intro"})
    old = (datetime.now(timezone.utc) - timedelta(hours=1)).replace(tzinfo=None)
    api.session.execute(text("UPDATE segments SET status = 'running', attempts = 1, "
                             "claimed_by = 'dead-worker', claimed_at = :t"),
                        {"t": old.isoformat(sep=" ")})
    api.session.execute(text("UPDATE jobs SET status = 'running'"))
    api.session.commit()

    assert sweep_stale_segments(api.session, NullEvents(),
                                RetryPolicy(max_attempts=3, lease_seconds=900)) == 1
    assert _segment(api, job["id"])[:2] == ("queued", 1)
    assert api.call("GET", f"/api/jobs/{job['id']}").json()["status"] == "pending"
    (payload,) = _actions(api, "segment_recovered")
    assert "dead-worker" in payload
    run_worker(api)
    assert api.call("GET", f"/api/jobs/{job['id']}").json()["status"] == "awaiting_approval"
    assert api.call("GET", "/api/metrics").json()["reliability"]["recovered_segments"] == 1


def test_a_segment_past_its_attempts_is_dead_lettered_by_the_sweep(api):
    job = submit(api, {"brief": "intro"})
    api.session.execute(text("UPDATE segments SET status = 'running', attempts = 3, "
                             "claimed_at = NULL"))
    api.session.commit()
    sweep_stale_segments(api.session, NullEvents(), RetryPolicy(max_attempts=3))
    assert _segment(api, job["id"])[0] == "dead_letter"
    assert api.call("GET", f"/api/jobs/{job['id']}").json()["status"] == "failed"


# ------------------------------------------------------------------ budgets (cat 3)

def test_the_daily_model_budget_defers_new_segments_to_tomorrow(api, monkeypatch):
    monkeypatch.setattr(get_settings(), "max_llm_calls_per_day", 1)
    first = submit(api, {"brief": "one"})
    run_worker(api)  # one stub run: the day's budget is now spent
    second = submit(api, {"brief": "two"})
    assert run_once(api.session, StubOrchestrator(), NullEvents()) is True
    status, attempts, _, not_before, _ = _segment(api, second["id"])
    assert (status, attempts) == ("queued", 0)
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).date().isoformat()
    assert str(not_before).startswith(tomorrow)
    assert run_once(api.session, StubOrchestrator(), NullEvents()) is False
    (payload,) = _actions(api, "budget_deferred")
    assert '"daily_limit": 1' in payload
    assert api.call("GET", f"/api/jobs/{first['id']}").json()["status"] == "awaiting_approval"
    assert api.call("GET", "/api/metrics").json()["reliability"]["budget_deferrals"] == 1


# ------------------------------------------------------------------ fallback (cat 4)

def test_with_ollama_down_a_segment_runs_on_the_stub_and_says_so(api):
    selector = OrchestratorSelector(available=lambda url: False,
                                    crew_factory=lambda: pytest.fail("crew must not run"))
    job = submit(api, {"brief": "intro"})
    assert run_once(api.session, selector, NullEvents()) is True
    assert api.call("GET", f"/api/jobs/{job['id']}").json()["status"] == "awaiting_approval"
    (payload,) = _actions(api, "orchestrator_fallback")
    assert '"model_id": "stub"' in payload and "unreachable" in payload
    models = api.session.execute(text("SELECT model_id FROM agent_run")).scalars().all()
    assert models == ["stub"]
    assert api.call("GET", "/api/metrics").json()["reliability"]["fallback_runs"] == 1


# ------------------------------------------------------------------ lineage (section 6)

def test_runs_carry_their_segment_and_the_task_their_gate_created(api):
    job = submit(api, {"brief": "intro"})
    run_worker(api)
    seg_id, task_id = api.session.execute(text(
        "SELECT s.id, t.id FROM segments s JOIN task t ON t.job_id = s.job_id "
        "WHERE s.job_id = :j"), {"j": job["id"]}).one()
    runs = api.session.execute(text("SELECT segment_id, task_id FROM agent_run")).all()
    assert runs == [(seg_id, task_id)]


def test_a_rejected_handoff_in_the_worker_keeps_its_audit_row(api, monkeypatch):
    import aura.core.services.run_segment as rs
    monkeypatch.setattr(rs, "build_gate_package", lambda *a, **k: {"what_happened": []})
    job = submit(api, {"brief": "intro"})
    run_worker(api)
    assert _segment(api, job["id"])[0] == "failed"
    assert len(_actions(api, "handoff_rejected")) == 1
    (failed,) = _actions(api, "segment_failed")
    assert '"permanent": true' in failed
    assert api.call("GET", f"/api/jobs/{job['id']}").json()["status"] == "failed"


# ------------------------------------------------------------------ resolve race (cat 7)

def test_two_concurrent_resolves_cannot_both_win(file_engine):
    with Session(file_engine) as s:
        from aura.data.seed import seed_reference
        seed_reference(s)
        (seg_id,) = _queue(s, 1)
        s.execute(text("UPDATE segments SET status = 'awaiting_approval'"))
        package = build_gate_package(
            ProposedAction(tool="send_email", category=ActionCategory.OUTBOUND,
                           arguments={"to": "ravi"}, summary="Send intro"),
            datetime.now(timezone.utc))
        handoff = create_handoff(
            deal_id=None, job_id=1, task_type="send_email",
            assignment_mode=AssignmentMode.HUMAN_REQUIRED,
            direction=HandoffDirection.BOT_TO_HUMAN, trigger=HandoffTrigger.POLICY_REQUIRED,
            context_package=package, directive=None, materiality_inr=None, actor="system",
            tasks=SqlTaskRepository(s, SYSTEM), handoffs=SqlHandoffRepository(s, SYSTEM),
            audit=SqlAuditRepository(s, SYSTEM), events=NullEvents())
        s.commit()

    both_read = threading.Barrier(2, timeout=10)
    results: dict[str, str] = {}

    class RacingHandoffs(SqlHandoffRepository):
        def get(self, handoff_id):
            found = super().get(handoff_id)
            both_read.wait()  # both resolvers have seen it OPEN before either writes
            return found

    def resolver(name):
        with Session(file_engine) as s:
            try:
                resolve_handoff(handoff.id, DIRECTIVE, name, Role.DEALMAKER,
                                SqlJobRepository(s, SYSTEM), SqlSegmentRepository(s),
                                SqlTaskRepository(s, SYSTEM), RacingHandoffs(s, SYSTEM),
                                SqlDocumentRepository(s, SYSTEM),
                                SqlAuditRepository(s, SYSTEM), NullEvents())
                s.commit()
                results[name] = "won"
            except Conflict:
                s.rollback()
                results[name] = "conflict"

    threads = [threading.Thread(target=resolver, args=(n,)) for n in ("bhavesh", "asha")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert sorted(results.values()) == ["conflict", "won"]
    with Session(file_engine) as s:
        assert s.execute(text("SELECT COUNT(*) FROM audit_entries "
                              "WHERE action = 'handoff_resolved'")).scalar() == 1
        assert s.execute(text("SELECT COUNT(*) FROM segments")).scalar() == 2  # one n+1
        winner = s.execute(text("SELECT resolved_by, status FROM handoff")).one()
    assert winner == ([n for n, r in results.items() if r == "won"][0],
                      HandoffStatus.RESOLVED.value)


def test_resolving_twice_over_the_api_is_a_409(api):
    submit(api, {"brief": "intro"})
    run_worker(api)
    (h,) = api.call("GET", "/api/handoffs?status=open").json()
    assert api.call("POST", f"/api/handoffs/{h['id']}/resolve", json=DIRECTIVE).status_code \
        == 200
    assert api.call("POST", f"/api/handoffs/{h['id']}/resolve", json=DIRECTIVE).status_code \
        == 409


# ------------------------------------------------------------------ idempotency (cat 1)

def _post(api, body, key=None, user="bhavesh"):
    headers = {**api.as_user(user), **({"Idempotency-Key": key} if key else {})}
    return api.client.post("/api/jobs", json=body, headers=headers)



def test_an_idempotency_key_returns_the_original_job(api):
    body = {"inputs": {"brief": "intro"}, "deal_id": None}
    first = _post(api, body, key="abc-1")
    assert first.status_code == 202
    again = _post(api, body, key="abc-1")
    assert again.status_code == 200 and again.headers["Idempotent-Replayed"] == "true"
    assert again.json()["id"] == first.json()["id"]
    assert api.session.execute(text("SELECT COUNT(*) FROM jobs")).scalar() == 1

    clash = _post(api, {"inputs": {"brief": "other"}, "deal_id": None}, key="abc-1")
    assert clash.status_code == 409
    # keys belong to their user; no key means no deduplication
    assert _post(api, body, key="abc-1", user="asha").json()["id"] != first.json()["id"]
    assert _post(api, body).json()["id"] != _post(api, body).json()["id"]


def test_an_idempotency_key_expires_after_a_day(api):
    body = {"inputs": {"brief": "intro"}, "deal_id": None}
    first = _post(api, body, key="k").json()
    day_ago = (datetime.now(timezone.utc) - timedelta(hours=25)).replace(tzinfo=None)
    api.session.execute(text("UPDATE idempotency_key SET created_at = :t"),
                        {"t": day_ago.isoformat(sep=" ")})
    api.session.commit()
    fresh = _post(api, body, key="k")
    assert fresh.status_code == 202 and fresh.json()["id"] != first["id"]
    assert api.session.execute(text("SELECT COUNT(*) FROM idempotency_key")).scalar() == 1
