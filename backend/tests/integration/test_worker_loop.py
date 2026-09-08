from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import Session

from aura.core.domain.enums import ApprovalStatus, JobStatus, SegmentStatus
from aura.core.domain.job import Job
from aura.core.domain.segment import Segment
from aura.data.engine import Base, make_engine
from aura.data.repositories.sql import (SqlApprovalRepository, SqlAuditRepository,
                                        SqlJobRepository, SqlSegmentRepository)
from aura.worker.runner import run_once
from aura.worker.stub_orchestrator import StubOrchestrator


class NullEvents:
    def publish(self, event_type: str, payload: dict) -> None:
        pass


@pytest.fixture()
def session():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def test_worker_runs_queued_segment_and_stops_at_gate(session):
    jobs, segs = SqlJobRepository(session), SqlSegmentRepository(session)
    approvals = SqlApprovalRepository(session)
    job = jobs.add(Job(id=None, status=JobStatus.PENDING, inputs={"brief": "x"},
                       deal_id=None, result=None, created_at=datetime.now(timezone.utc)))
    segs.add(Segment(id=None, job_id=job.id, seq=1, status=SegmentStatus.QUEUED,
                     context_in={"brief": "x"}, context_out=None,
                     started_at=None, ended_at=None))

    did_work = run_once(session, StubOrchestrator(), NullEvents())

    assert did_work is True
    assert jobs.get(job.id).status is JobStatus.AWAITING_APPROVAL
    pending = approvals.list_pending()
    assert len(pending) == 1
    assert pending[0].status is ApprovalStatus.PENDING


def test_worker_returns_false_when_nothing_queued(session):
    assert run_once(session, StubOrchestrator(), NullEvents()) is False
