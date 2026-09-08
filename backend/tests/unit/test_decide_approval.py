from datetime import datetime, timezone

import pytest

from aura.core.domain.approval import Approval
from aura.core.domain.enums import (ActionCategory, ApprovalStatus, JobStatus,
                                    SegmentStatus)
from aura.core.domain.job import Job
from aura.core.domain.segment import Segment
from aura.core.services.decide_approval import decide_approval
from tests.unit.fakes import (FakeApprovalRepo, FakeAuditRepo, FakeEvents,
                              FakeJobRepo, FakeSegmentRepo)


def _seed_awaiting():
    jobs, segments = FakeJobRepo(), FakeSegmentRepo()
    approvals, audit, events = FakeApprovalRepo(), FakeAuditRepo(), FakeEvents()
    job = jobs.add(Job(id=None, status=JobStatus.AWAITING_APPROVAL, inputs={},
                       deal_id=None, result=None, created_at=datetime.now(timezone.utc)))
    seg = segments.add(Segment(id=None, job_id=job.id, seq=1,
                               status=SegmentStatus.AWAITING_APPROVAL,
                               context_in={}, context_out={"draft": "hi"},
                               started_at=None, ended_at=None))
    appr = approvals.add(Approval(id=None, segment_id=seg.id,
                                  category=ActionCategory.OUTBOUND,
                                  proposed_action={"tool": "send_email"},
                                  status=ApprovalStatus.PENDING))
    return job, seg, appr, jobs, segments, approvals, audit, events


def test_approve_spawns_next_segment_seeded_from_context_out():
    job, seg, appr, jobs, segments, approvals, audit, events = _seed_awaiting()

    decide_approval(appr.id, approved=True, user_id=1, actor="bhavesh",
                    jobs=jobs, segments=segments, approvals=approvals,
                    audit=audit, events=events)

    segs = sorted(segments.list_for_job(job.id), key=lambda s: s.seq)
    assert len(segs) == 2
    assert segs[1].seq == 2
    assert segs[1].status is SegmentStatus.QUEUED
    assert segs[1].context_in == {"draft": "hi"}
    assert approvals.get(appr.id).status is ApprovalStatus.APPROVED


def test_reject_marks_job_rejected_and_creates_no_segment():
    job, seg, appr, jobs, segments, approvals, audit, events = _seed_awaiting()

    decide_approval(appr.id, approved=False, user_id=1, actor="bhavesh",
                    jobs=jobs, segments=segments, approvals=approvals,
                    audit=audit, events=events)

    assert approvals.get(appr.id).status is ApprovalStatus.REJECTED
    assert jobs.get(job.id).status is JobStatus.REJECTED
    assert len(segments.list_for_job(job.id)) == 1


def test_decision_is_audited_with_deciding_user():
    _, _, appr, jobs, segments, approvals, audit, events = _seed_awaiting()
    decide_approval(appr.id, approved=True, user_id=7, actor="bhavesh",
                    jobs=jobs, segments=segments, approvals=approvals,
                    audit=audit, events=events)
    entry = audit.entries[-1]
    assert entry.action == "approval_decided"
    assert entry.payload["approved"] is True
    assert entry.payload["decided_by"] == 7


def test_deciding_twice_raises():
    _, _, appr, jobs, segments, approvals, audit, events = _seed_awaiting()
    decide_approval(appr.id, True, 1, "bhavesh", jobs, segments, approvals, audit, events)
    with pytest.raises(ValueError):
        decide_approval(appr.id, True, 1, "bhavesh", jobs, segments, approvals, audit, events)
