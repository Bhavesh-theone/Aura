from datetime import datetime, timezone

from aura.core.domain.enums import (ActionCategory, AssignmentMode, HandoffDirection,
                                    HandoffStatus, HandoffTrigger, JobStatus, SegmentStatus,
                                    TaskStatus)
from aura.core.domain.job import Job
from aura.core.domain.segment import ProposedAction, Segment
from aura.core.policy.handoff_policy import validate_bot_to_human
from aura.core.ports.orchestrator import OrchestratorResult
from aura.core.services.run_segment import run_segment
from tests.unit.fakes import (FakeAuditRepo, FakeEvents, FakeHandoffRepo, FakeJobRepo,
                              FakeRunSink, FakeSegmentRepo, FakeTaskRepo, FakeUow)


class CompletingOrchestrator:
    def run(self, context_in: dict, run_context) -> OrchestratorResult:
        return OrchestratorResult(completed=True, context_out={"draft": "hello"},
                                  proposed_action=None)


class GatingOrchestrator:
    def __init__(self, action=None):
        self.action = action or ProposedAction(
            tool="send_email", category=ActionCategory.OUTBOUND,
            arguments={"to": "ravi@x.com"}, summary="Send intro email")

    def run(self, context_in: dict, run_context) -> OrchestratorResult:
        return OrchestratorResult(completed=False, context_out={"draft": "Dear Ravi..."},
                                  proposed_action=self.action)


class ExplodingOrchestrator:
    def run(self, context_in: dict, run_context) -> OrchestratorResult:
        raise RuntimeError("model fell over")


class World:
    def __init__(self, deal_id=None):
        self.jobs, self.segments = FakeJobRepo(), FakeSegmentRepo()
        self.tasks, self.handoffs = FakeTaskRepo(), FakeHandoffRepo()
        self.audit, self.events = FakeAuditRepo(), FakeEvents()
        self.runs, self.uow = FakeRunSink(), FakeUow()
        self.job = self.jobs.add(Job(id=None, status=JobStatus.PENDING, inputs={},
                                     deal_id=deal_id, result=None,
                                     created_at=datetime.now(timezone.utc)))
        self.seg = self.segments.add(Segment(id=None, job_id=self.job.id, seq=1,
                                             status=SegmentStatus.QUEUED, context_in={},
                                             context_out=None, started_at=None,
                                             ended_at=None))

    def run(self, orchestrator, **kw):
        run_segment(self.seg.id, orchestrator, self.jobs, self.segments, self.tasks,
                    self.handoffs, self.audit, self.events, self.runs, self.uow, **kw)


def test_completing_run_marks_job_complete():
    w = World()
    w.run(CompletingOrchestrator())
    assert w.segments.get(w.seg.id).status is SegmentStatus.DONE
    assert w.jobs.get(w.job.id).status is JobStatus.COMPLETE
    assert w.handoffs.open_ones() == []


def test_gated_run_ends_segment_and_creates_task_and_handoff():
    w = World(deal_id=7)
    w.run(GatingOrchestrator())

    assert w.segments.get(w.seg.id).status is SegmentStatus.AWAITING_APPROVAL
    assert w.segments.get(w.seg.id).context_out == {"draft": "Dear Ravi..."}
    assert w.jobs.get(w.job.id).status is JobStatus.AWAITING_APPROVAL

    (handoff,) = w.handoffs.open_ones()
    task = w.tasks.get(handoff.task_id)
    assert handoff.direction is HandoffDirection.BOT_TO_HUMAN
    assert handoff.trigger is HandoffTrigger.POLICY_REQUIRED
    assert handoff.status is HandoffStatus.OPEN and handoff.deal_id == 7
    assert task.job_id == w.job.id and task.task_type == "send_email"
    assert task.assignment_mode is AssignmentMode.HUMAN_REQUIRED
    assert task.status is TaskStatus.REVIEW


def test_gate_builds_a_valid_package_from_the_proposed_action():
    w = World()
    w.run(GatingOrchestrator())
    (handoff,) = w.handoffs.open_ones()
    validate_bot_to_human(handoff.context_package)  # would raise if incomplete
    decision = handoff.context_package["decision_required"]
    assert [o["id"] for o in decision["options"]] == ["approve", "reject"]
    assert decision["recommendation"] == "approve"
    nothing = handoff.context_package["if_you_do_nothing"]
    assert nothing["consequence"].startswith("Job stays paused; escalates to dealmaker at ")
    assert nothing["escalates_to_role"] == "dealmaker"
    assert handoff.auto_escalate_at is not None


def test_gated_run_publishes_handoff_created_and_audits_it():
    w = World()
    w.run(GatingOrchestrator())
    assert any(e[0] == "handoff_created" for e in w.events.published)
    assert "handoff_created" in [e.action for e in w.audit.entries]


def test_no_second_segment_is_created_before_a_decision():
    w = World()
    w.run(GatingOrchestrator())
    assert len(w.segments.list_for_job(w.job.id)) == 1


def test_materiality_above_the_cap_gates_even_an_ungated_category():
    w = World()
    action = ProposedAction(tool="add_internal_note", category=ActionCategory.INTERNAL_WRITE,
                            arguments={}, summary="Record a note on a big payment",
                            materiality_inr=60_000_000)
    w.run(GatingOrchestrator(action))
    (handoff,) = w.handoffs.open_ones()
    assert handoff.trigger is HandoffTrigger.MATERIALITY_GATE
    assert handoff.context_package["decision_required"]["recommendation"] == "reject"
    assert w.tasks.get(handoff.task_id).materiality_inr == 60_000_000


def test_ungated_category_below_the_cap_does_not_gate():
    w = World()
    action = ProposedAction(tool="add_internal_note", category=ActionCategory.INTERNAL_WRITE,
                            arguments={}, summary="note", materiality_inr=49_999_999)
    w.run(GatingOrchestrator(action))
    assert w.jobs.get(w.job.id).status is JobStatus.COMPLETE


def test_cap_is_configurable():
    w = World()
    action = ProposedAction(tool="add_internal_note", category=ActionCategory.INTERNAL_WRITE,
                            arguments={}, summary="note", materiality_inr=2_000)
    w.run(GatingOrchestrator(action), materiality_cap_inr=1_000)
    assert len(w.handoffs.open_ones()) == 1


def test_orchestrator_failure_fails_the_job_and_rolls_back():
    w = World()
    w.run(ExplodingOrchestrator())
    assert w.jobs.get(w.job.id).status is JobStatus.FAILED
    assert w.segments.get(w.seg.id).status is SegmentStatus.FAILED
    assert w.uow.rollbacks == 1
    assert w.audit.entries[-1].action == "segment_failed"
    assert w.handoffs.open_ones() == []


def test_running_mark_commits_before_the_model_runs():
    w = World()
    seen = {}

    class Probe:
        def run(self, context_in, run_context):
            seen["commits_before_run"] = w.uow.commits
            return OrchestratorResult(completed=True, context_out={}, proposed_action=None)

    w.run(Probe())
    assert seen["commits_before_run"] == 1 and w.uow.commits == 2
