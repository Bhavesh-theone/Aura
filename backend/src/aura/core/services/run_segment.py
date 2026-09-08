from dataclasses import asdict
from datetime import datetime, timezone

from aura.core.domain.approval import Approval
from aura.core.domain.audit import AuditEntry
from aura.core.domain.enums import ApprovalStatus, JobStatus, SegmentStatus
from aura.core.policy.gate_policy import requires_approval
from aura.core.ports.events import EventPublisher
from aura.core.ports.orchestrator import Orchestrator
from aura.core.ports.repositories import (ApprovalRepository, AuditRepository,
                                          JobRepository, SegmentRepository)


def run_segment(
    segment_id: int,
    orchestrator: Orchestrator,
    jobs: JobRepository,
    segments: SegmentRepository,
    approvals: ApprovalRepository,
    audit: AuditRepository,
    events: EventPublisher,
) -> None:
    """Run one segment to completion or to a gate. Never blocks on a human."""
    segment = segments.get(segment_id)
    if segment is None:
        raise ValueError(f"segment {segment_id} not found")

    job = jobs.get(segment.job_id)
    now = datetime.now(timezone.utc)

    segment.status = SegmentStatus.RUNNING
    segment.started_at = now
    segments.update(segment)
    job.status = JobStatus.RUNNING
    jobs.update(job)

    try:
        result = orchestrator.run(segment.context_in)
    except Exception as exc:
        segment.status = SegmentStatus.FAILED
        segment.ended_at = datetime.now(timezone.utc)
        segments.update(segment)
        job.status = JobStatus.FAILED
        jobs.update(job)
        audit.append(AuditEntry(id=None, job_id=job.id, actor="system",
                                action="segment_failed",
                                payload={"segment_id": segment.id, "error": str(exc)},
                                created_at=datetime.now(timezone.utc)))
        events.publish("job_failed", {"job_id": job.id})
        return

    ended = datetime.now(timezone.utc)
    segment.context_out = result.context_out
    segment.ended_at = ended

    action = result.proposed_action
    if action is not None and requires_approval(action.category):
        segment.status = SegmentStatus.AWAITING_APPROVAL
        segments.update(segment)

        approval = approvals.add(Approval(id=None, segment_id=segment.id,
                                          category=action.category,
                                          proposed_action=asdict(action),
                                          status=ApprovalStatus.PENDING))
        job.status = JobStatus.AWAITING_APPROVAL
        jobs.update(job)

        audit.append(AuditEntry(id=None, job_id=job.id, actor="system",
                                action="approval_requested",
                                payload={"approval_id": approval.id,
                                         "category": action.category.value,
                                         "summary": action.summary},
                                created_at=ended))
        events.publish("approval_required",
                       {"job_id": job.id, "approval_id": approval.id,
                        "category": action.category.value, "summary": action.summary})
        return

    segment.status = SegmentStatus.DONE
    segments.update(segment)
    job.status = JobStatus.COMPLETE
    job.result = result.context_out
    jobs.update(job)

    audit.append(AuditEntry(id=None, job_id=job.id, actor="system", action="job_completed",
                            payload={"segment_id": segment.id}, created_at=ended))
    events.publish("job_complete", {"job_id": job.id})
