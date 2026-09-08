from datetime import datetime, timezone

from aura.core.domain.enums import (ActionCategory, ApprovalStatus, JobStatus,
                                    SegmentStatus)
from aura.core.domain.job import Job
from aura.core.domain.segment import ProposedAction, Segment
from aura.core.ports.orchestrator import OrchestratorResult
from aura.core.services.run_segment import run_segment
from tests.unit.fakes import (FakeApprovalRepo, FakeAuditRepo, FakeEvents,
                              FakeJobRepo, FakeSegmentRepo)


class CompletingOrchestrator:
    def run(self, context_in: dict) -> OrchestratorResult:
        return OrchestratorResult(completed=True, context_out={"draft": "hello"},
                                  proposed_action=None)


class GatingOrchestrator:
    def run(self, context_in: dict) -> OrchestratorResult:
        return OrchestratorResult(
            completed=False,
            context_out={"draft": "Dear Ravi..."},
            proposed_action=ProposedAction(tool="send_email",
                                           category=ActionCategory.OUTBOUND,
                                           arguments={"to": "ravi@x.com"},
                                           summary="Send intro email"),
        )


def _seed():
    jobs, segments = FakeJobRepo(), FakeSegmentRepo()
    approvals, audit, events = FakeApprovalRepo(), FakeAuditRepo(), FakeEvents()
    job = jobs.add(Job(id=None, status=JobStatus.PENDING, inputs={}, deal_id=None,
                       result=None, created_at=datetime.now(timezone.utc)))
    seg = segments.add(Segment(id=None, job_id=job.id, seq=1, status=SegmentStatus.QUEUED,
                               context_in={}, context_out=None, started_at=None, ended_at=None))
    return job, seg, jobs, segments, approvals, audit, events


def test_completing_run_marks_job_complete():
    job, seg, jobs, segments, approvals, audit, events = _seed()

    run_segment(seg.id, CompletingOrchestrator(), jobs, segments, approvals, audit, events)

    assert segments.get(seg.id).status is SegmentStatus.DONE
    assert jobs.get(job.id).status is JobStatus.COMPLETE
    assert approvals.list_pending() == []


def test_gated_run_ends_segment_and_creates_approval():
    job, seg, jobs, segments, approvals, audit, events = _seed()

    run_segment(seg.id, GatingOrchestrator(), jobs, segments, approvals, audit, events)

    updated = segments.get(seg.id)
    assert updated.status is SegmentStatus.AWAITING_APPROVAL
    assert updated.context_out == {"draft": "Dear Ravi..."}
    assert jobs.get(job.id).status is JobStatus.AWAITING_APPROVAL

    pending = approvals.list_pending()
    assert len(pending) == 1
    assert pending[0].category is ActionCategory.OUTBOUND
    assert pending[0].status is ApprovalStatus.PENDING


def test_gated_run_publishes_approval_required():
    _, seg, jobs, segments, approvals, audit, events = _seed()
    run_segment(seg.id, GatingOrchestrator(), jobs, segments, approvals, audit, events)
    assert any(e[0] == "approval_required" for e in events.published)


def test_no_second_segment_is_created_before_approval():
    job, seg, jobs, segments, approvals, audit, events = _seed()
    run_segment(seg.id, GatingOrchestrator(), jobs, segments, approvals, audit, events)
    assert len(segments.list_for_job(job.id)) == 1
