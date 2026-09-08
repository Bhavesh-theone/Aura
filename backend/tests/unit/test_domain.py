from datetime import datetime, timezone

from aura.core.domain.enums import ActionCategory, JobStatus, SegmentStatus
from aura.core.domain.job import Job
from aura.core.domain.segment import Segment, ProposedAction


def test_job_starts_pending():
    job = Job(id=None, status=JobStatus.PENDING, inputs={"brief": "draft intro"},
              deal_id=None, result=None, created_at=datetime.now(timezone.utc))
    assert job.status is JobStatus.PENDING


def test_segment_sequence_starts_at_one():
    seg = Segment(id=None, job_id=1, seq=1, status=SegmentStatus.QUEUED,
                  context_in={}, context_out=None, started_at=None, ended_at=None)
    assert seg.seq == 1
    assert seg.context_out is None


def test_proposed_action_carries_category():
    action = ProposedAction(tool="send_email", category=ActionCategory.OUTBOUND,
                            arguments={"to": "a@b.com"}, summary="Send intro email")
    assert action.category is ActionCategory.OUTBOUND
