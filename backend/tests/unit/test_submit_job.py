from aura.core.domain.enums import JobStatus, SegmentStatus
from aura.core.services.submit_job import submit_job
from tests.unit.fakes import FakeAuditRepo, FakeEvents, FakeJobRepo, FakeSegmentRepo


def test_submit_creates_job_and_first_segment():
    jobs, segments, audit, events = FakeJobRepo(), FakeSegmentRepo(), FakeAuditRepo(), FakeEvents()

    job = submit_job(inputs={"brief": "draft intro to D-002"}, deal_id=2, actor="bhavesh",
                     jobs=jobs, segments=segments, audit=audit, events=events)

    assert job.id == 1
    assert job.status is JobStatus.PENDING

    segs = segments.list_for_job(job.id)
    assert len(segs) == 1
    assert segs[0].seq == 1
    assert segs[0].status is SegmentStatus.QUEUED
    assert segs[0].context_in == {"brief": "draft intro to D-002"}


def test_submit_writes_audit_entry():
    jobs, segments, audit, events = FakeJobRepo(), FakeSegmentRepo(), FakeAuditRepo(), FakeEvents()
    submit_job(inputs={}, deal_id=None, actor="bhavesh",
               jobs=jobs, segments=segments, audit=audit, events=events)
    assert audit.entries[0].action == "job_submitted"
    assert audit.entries[0].actor == "bhavesh"


def test_submit_publishes_event():
    jobs, segments, audit, events = FakeJobRepo(), FakeSegmentRepo(), FakeAuditRepo(), FakeEvents()
    submit_job(inputs={}, deal_id=None, actor="bhavesh",
               jobs=jobs, segments=segments, audit=audit, events=events)
    assert events.published[0][0] == "job_submitted"
