from sqlalchemy import select
from sqlalchemy.orm import Session

from aura.core.domain.approval import Approval
from aura.core.domain.audit import AuditEntry
from aura.core.domain.enums import ApprovalStatus, SegmentStatus
from aura.core.domain.job import Job
from aura.core.domain.segment import Segment
from aura.core.domain.user import User
from aura.data import mappers
from aura.data.models.tables import (ApprovalRow, AuditRow, JobRow, SegmentRow,
                                     UserRow)


class SqlJobRepository:
    def __init__(self, session: Session):
        self.s = session

    def add(self, job: Job) -> Job:
        row = JobRow(status=job.status.value, inputs=job.inputs, result=job.result,
                     deal_id=job.deal_id, created_at=job.created_at)
        self.s.add(row)
        self.s.commit()
        self.s.refresh(row)
        return mappers.job_to_domain(row)

    def get(self, job_id: int) -> Job | None:
        row = self.s.get(JobRow, job_id)
        return mappers.job_to_domain(row) if row else None

    def update(self, job: Job) -> Job:
        row = self.s.get(JobRow, job.id)
        row.status, row.result = job.status.value, job.result
        self.s.commit()
        self.s.refresh(row)
        return mappers.job_to_domain(row)

    def list_recent(self, limit: int = 50) -> list[Job]:
        rows = self.s.scalars(select(JobRow).order_by(JobRow.id.desc()).limit(limit)).all()
        return [mappers.job_to_domain(r) for r in rows]


class SqlSegmentRepository:
    def __init__(self, session: Session):
        self.s = session

    def add(self, segment: Segment) -> Segment:
        row = SegmentRow(job_id=segment.job_id, seq=segment.seq, status=segment.status.value,
                         context_in=segment.context_in, context_out=segment.context_out,
                         started_at=segment.started_at, ended_at=segment.ended_at)
        self.s.add(row)
        self.s.commit()
        self.s.refresh(row)
        return mappers.segment_to_domain(row)

    def get(self, segment_id: int) -> Segment | None:
        row = self.s.get(SegmentRow, segment_id)
        return mappers.segment_to_domain(row) if row else None

    def update(self, segment: Segment) -> Segment:
        row = self.s.get(SegmentRow, segment.id)
        row.status = segment.status.value
        row.context_out = segment.context_out
        row.started_at, row.ended_at = segment.started_at, segment.ended_at
        self.s.commit()
        self.s.refresh(row)
        return mappers.segment_to_domain(row)

    def claim_next_queued(self) -> Segment | None:
        row = self.s.scalars(
            select(SegmentRow).where(SegmentRow.status == SegmentStatus.QUEUED.value)
            .order_by(SegmentRow.id.asc()).limit(1)
        ).first()
        return mappers.segment_to_domain(row) if row else None

    def list_for_job(self, job_id: int) -> list[Segment]:
        rows = self.s.scalars(
            select(SegmentRow).where(SegmentRow.job_id == job_id).order_by(SegmentRow.seq)
        ).all()
        return [mappers.segment_to_domain(r) for r in rows]


class SqlApprovalRepository:
    def __init__(self, session: Session):
        self.s = session

    def add(self, approval: Approval) -> Approval:
        row = ApprovalRow(segment_id=approval.segment_id, category=approval.category.value,
                          proposed_action=approval.proposed_action,
                          status=approval.status.value, decided_by=approval.decided_by,
                          decided_at=approval.decided_at)
        self.s.add(row)
        self.s.commit()
        self.s.refresh(row)
        return mappers.approval_to_domain(row)

    def get(self, approval_id: int) -> Approval | None:
        row = self.s.get(ApprovalRow, approval_id)
        return mappers.approval_to_domain(row) if row else None

    def update(self, approval: Approval) -> Approval:
        row = self.s.get(ApprovalRow, approval.id)
        row.status = approval.status.value
        row.decided_by, row.decided_at = approval.decided_by, approval.decided_at
        self.s.commit()
        self.s.refresh(row)
        return mappers.approval_to_domain(row)

    def list_pending(self) -> list[Approval]:
        rows = self.s.scalars(
            select(ApprovalRow).where(ApprovalRow.status == ApprovalStatus.PENDING.value)
            .order_by(ApprovalRow.id.desc())
        ).all()
        return [mappers.approval_to_domain(r) for r in rows]


class SqlAuditRepository:
    """Append-only by design - no update or delete method exists."""

    def __init__(self, session: Session):
        self.s = session

    def append(self, entry: AuditEntry) -> AuditEntry:
        row = AuditRow(job_id=entry.job_id, actor=entry.actor, action=entry.action,
                       payload=entry.payload, created_at=entry.created_at)
        self.s.add(row)
        self.s.commit()
        self.s.refresh(row)
        return mappers.audit_to_domain(row)

    def list_recent(self, limit: int = 100) -> list[AuditEntry]:
        rows = self.s.scalars(select(AuditRow).order_by(AuditRow.id.desc()).limit(limit)).all()
        return [mappers.audit_to_domain(r) for r in rows]


class SqlUserRepository:
    def __init__(self, session: Session):
        self.s = session

    def get_by_username(self, username: str) -> User | None:
        row = self.s.scalars(select(UserRow).where(UserRow.username == username)).first()
        return mappers.user_to_domain(row) if row else None

    def get(self, user_id: int) -> User | None:
        row = self.s.get(UserRow, user_id)
        return mappers.user_to_domain(row) if row else None
