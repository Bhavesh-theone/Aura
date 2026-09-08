"""ORM <-> domain translation. ORM rows never escape the data package."""
from aura.core.domain.approval import Approval
from aura.core.domain.audit import AuditEntry
from aura.core.domain.enums import (ActionCategory, ApprovalStatus, JobStatus,
                                    Role, SegmentStatus)
from aura.core.domain.job import Job
from aura.core.domain.segment import Segment
from aura.core.domain.user import User
from aura.data.models.tables import (ApprovalRow, AuditRow, JobRow, SegmentRow,
                                     UserRow)


def job_to_domain(row: JobRow) -> Job:
    return Job(id=row.id, status=JobStatus(row.status), inputs=row.inputs or {},
               deal_id=row.deal_id, result=row.result, created_at=row.created_at)


def segment_to_domain(row: SegmentRow) -> Segment:
    return Segment(id=row.id, job_id=row.job_id, seq=row.seq,
                   status=SegmentStatus(row.status), context_in=row.context_in or {},
                   context_out=row.context_out, started_at=row.started_at,
                   ended_at=row.ended_at)


def approval_to_domain(row: ApprovalRow) -> Approval:
    return Approval(id=row.id, segment_id=row.segment_id,
                    category=ActionCategory(row.category),
                    proposed_action=row.proposed_action or {},
                    status=ApprovalStatus(row.status), decided_by=row.decided_by,
                    decided_at=row.decided_at)


def audit_to_domain(row: AuditRow) -> AuditEntry:
    return AuditEntry(id=row.id, job_id=row.job_id, actor=row.actor, action=row.action,
                      payload=row.payload or {}, created_at=row.created_at)


def user_to_domain(row: UserRow) -> User:
    return User(id=row.id, username=row.username, password_hash=row.password_hash,
                role=Role(row.role))
