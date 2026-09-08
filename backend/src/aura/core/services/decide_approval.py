from datetime import datetime, timezone

from aura.core.domain.approval import Approval
from aura.core.domain.audit import AuditEntry
from aura.core.domain.enums import ApprovalStatus, JobStatus, SegmentStatus
from aura.core.domain.segment import Segment
from aura.core.ports.events import EventPublisher
from aura.core.ports.repositories import (ApprovalRepository, AuditRepository,
                                          JobRepository, SegmentRepository)


def decide_approval(
    approval_id: int,
    approved: bool,
    user_id: int,
    actor: str,
    jobs: JobRepository,
    segments: SegmentRepository,
    approvals: ApprovalRepository,
    audit: AuditRepository,
    events: EventPublisher,
) -> Approval:
    """Record a human decision. On approval, queue the next segment seeded from context_out."""
    approval = approvals.get(approval_id)
    if approval is None:
        raise ValueError(f"approval {approval_id} not found")
    if approval.status is not ApprovalStatus.PENDING:
        raise ValueError(f"approval {approval_id} already decided")

    now = datetime.now(timezone.utc)
    segment = segments.get(approval.segment_id)
    job = jobs.get(segment.job_id)

    approval.status = ApprovalStatus.APPROVED if approved else ApprovalStatus.REJECTED
    approval.decided_by = user_id
    approval.decided_at = now
    approvals.update(approval)

    segment.status = SegmentStatus.DONE
    segments.update(segment)

    if approved:
        segments.add(Segment(id=None, job_id=job.id, seq=segment.seq + 1,
                             status=SegmentStatus.QUEUED,
                             context_in=dict(segment.context_out or {}),
                             context_out=None, started_at=None, ended_at=None))
        job.status = JobStatus.PENDING
    else:
        job.status = JobStatus.REJECTED
    jobs.update(job)

    audit.append(AuditEntry(id=None, job_id=job.id, actor=actor, action="approval_decided",
                            payload={"approval_id": approval.id, "approved": approved,
                                     "decided_by": user_id},
                            created_at=now))
    events.publish("approval_decided",
                   {"job_id": job.id, "approval_id": approval.id, "approved": approved})
    return approval
