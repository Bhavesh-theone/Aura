from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import Session

from aura.core.domain.enums import JobStatus, SegmentStatus
from aura.core.domain.job import Job
from aura.core.domain.segment import Segment
from aura.data.engine import Base, make_engine
from aura.data.repositories.sql import SqlJobRepository, SqlSegmentRepository


@pytest.fixture()
def session():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def test_job_roundtrips_as_domain_object(session):
    repo = SqlJobRepository(session)
    saved = repo.add(Job(id=None, status=JobStatus.PENDING, inputs={"brief": "x"},
                         deal_id=None, result=None, created_at=datetime.now(timezone.utc)))
    assert saved.id is not None

    fetched = repo.get(saved.id)
    assert isinstance(fetched, Job)
    assert fetched.inputs == {"brief": "x"}
    assert fetched.status is JobStatus.PENDING


def test_claim_next_queued_returns_only_queued_segments(session):
    jobs, segs = SqlJobRepository(session), SqlSegmentRepository(session)
    job = jobs.add(Job(id=None, status=JobStatus.PENDING, inputs={}, deal_id=None,
                       result=None, created_at=datetime.now(timezone.utc)))
    segs.add(Segment(id=None, job_id=job.id, seq=1, status=SegmentStatus.DONE,
                     context_in={}, context_out={}, started_at=None, ended_at=None))
    queued = segs.add(Segment(id=None, job_id=job.id, seq=2, status=SegmentStatus.QUEUED,
                              context_in={"a": 1}, context_out=None,
                              started_at=None, ended_at=None))

    claimed = segs.claim_next_queued()
    assert claimed.id == queued.id
    assert claimed.context_in == {"a": 1}
