from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import Session

from aura.core.domain.enums import HandoffStatus, JobStatus, SegmentStatus
from aura.core.domain.job import Job
from aura.core.domain.segment import Segment
from aura.data.repositories.sql import (SqlAgentRunRepository, SqlHandoffRepository,
                                        SqlJobRepository, SqlSegmentRepository)
from aura.data.walls import SYSTEM
from aura.worker.runner import run_once
from aura.worker.stub_orchestrator import StubOrchestrator
from tests.integration.pgtest import fresh_engine


class NullEvents:
    def publish(self, event_type: str, payload: dict) -> None:
        pass


@pytest.fixture()
def session():
    engine = fresh_engine()
    with Session(engine) as s:
        yield s


def test_worker_runs_queued_segment_and_stops_at_gate(session):
    jobs, segs = SqlJobRepository(session, SYSTEM), SqlSegmentRepository(session)
    handoffs = SqlHandoffRepository(session, SYSTEM)
    job = jobs.add(Job(id=None, status=JobStatus.PENDING, inputs={"brief": "x"},
                       deal_id=None, result=None, created_at=datetime.now(timezone.utc)))
    segs.add(Segment(id=None, job_id=job.id, seq=1, status=SegmentStatus.QUEUED,
                     context_in={"brief": "x"}, context_out=None,
                     started_at=None, ended_at=None))
    session.commit()

    did_work = run_once(session, StubOrchestrator(), NullEvents())

    assert did_work is True
    assert jobs.get(job.id).status is JobStatus.AWAITING_APPROVAL
    (open_handoff,) = handoffs.list_all(resolved=False)
    assert open_handoff.status is HandoffStatus.OPEN and open_handoff.job_id == job.id
    assert open_handoff.task_type == "send_email"
    # the stub's run is on record, tied to the job
    (run,) = SqlAgentRunRepository(session, SYSTEM).list_for()
    assert run.model_id == "stub" and run.job_id == job.id


def test_worker_returns_false_when_nothing_queued(session):
    assert run_once(session, StubOrchestrator(), NullEvents()) is False
