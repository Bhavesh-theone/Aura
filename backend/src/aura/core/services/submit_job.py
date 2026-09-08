from datetime import datetime, timezone

from aura.core.domain.audit import AuditEntry
from aura.core.domain.enums import JobStatus, SegmentStatus
from aura.core.domain.job import Job
from aura.core.domain.segment import Segment
from aura.core.ports.events import EventPublisher
from aura.core.ports.repositories import AuditRepository, JobRepository, SegmentRepository


def submit_job(
    inputs: dict,
    deal_id: int | None,
    actor: str,
    jobs: JobRepository,
    segments: SegmentRepository,
    audit: AuditRepository,
    events: EventPublisher,
) -> Job:
    """Create a job and queue its first segment. Returns immediately - no inference here."""
    now = datetime.now(timezone.utc)

    job = jobs.add(Job(id=None, status=JobStatus.PENDING, inputs=inputs,
                       deal_id=deal_id, result=None, created_at=now))

    segments.add(Segment(id=None, job_id=job.id, seq=1, status=SegmentStatus.QUEUED,
                         context_in=dict(inputs), context_out=None,
                         started_at=None, ended_at=None))

    audit.append(AuditEntry(id=None, job_id=job.id, actor=actor, action="job_submitted",
                            payload={"inputs": inputs, "deal_id": deal_id}, created_at=now))

    events.publish("job_submitted", {"job_id": job.id})
    return job
