"""Job, segment, audit, task, handoff, agent-run and user repositories.

None of these commit: they flush, and the unit of work that owns the session commits.
Deal-scoped ones take a `viewer` (see aura.data.walls) and only ever see deals behind walls
that viewer is on.
"""
import threading
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from aura.core.domain.agent_run import AgentRun
from aura.core.domain.audit import GENESIS_HASH, AuditEntry, compute_row_hash
from aura.core.domain.enums import HandoffStatus, Role, SegmentStatus
from aura.core.domain.handoff import Handoff, Task
from aura.core.domain.job import Job
from aura.core.domain.segment import Segment
from aura.core.domain.user import User
from aura.data import mappers
from aura.data.models.tables import (AgentRunRow, AuditRow, HandoffRow, JobRow, SegmentRow,
                                     TaskRow, UserRow)
from aura.data.walls import Viewer, check_viewer, walled

_AUDIT_LOCK = threading.Lock()


class SqlJobRepository:
    def __init__(self, session: Session, viewer: Viewer):
        self.s, self.viewer = session, check_viewer(viewer)

    def add(self, job: Job) -> Job:
        row = JobRow(status=job.status.value, inputs=job.inputs, result=job.result,
                     deal_id=job.deal_id, created_at=job.created_at,
                     created_by=job.created_by)
        self.s.add(row)
        self.s.flush()
        self.s.refresh(row)
        return mappers.job_to_domain(row)

    def get(self, job_id: int) -> Job | None:
        row = self.s.scalars(walled(select(JobRow).where(JobRow.id == job_id), self.viewer,
                                    JobRow.deal_id, include_unattached=True)).first()
        return mappers.job_to_domain(row) if row else None

    def update(self, job: Job) -> Job:
        row = self.s.get(JobRow, job.id)
        row.status, row.result = job.status.value, job.result
        self.s.flush()
        self.s.refresh(row)
        return mappers.job_to_domain(row)

    def list_recent(self, limit: int = 50) -> list[Job]:
        stmt = walled(select(JobRow), self.viewer, JobRow.deal_id, include_unattached=True)
        rows = self.s.scalars(stmt.order_by(JobRow.id.desc()).limit(limit)).all()
        return [mappers.job_to_domain(r) for r in rows]


class SqlSegmentRepository:
    """Segments hang off jobs and have no deal of their own; reach them through a job."""

    def __init__(self, session: Session):
        self.s = session

    def add(self, segment: Segment) -> Segment:
        row = SegmentRow(job_id=segment.job_id, seq=segment.seq, status=segment.status.value,
                         context_in=segment.context_in, context_out=segment.context_out,
                         started_at=segment.started_at, ended_at=segment.ended_at)
        self.s.add(row)
        self.s.flush()
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
        self.s.flush()
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


class SqlTaskRepository:
    def __init__(self, session: Session, viewer: Viewer):
        self.s, self.viewer = session, check_viewer(viewer)

    def add(self, task: Task) -> Task:
        row = TaskRow(deal_id=task.deal_id, job_id=task.job_id, task_type=task.task_type,
                      assignment_mode=task.assignment_mode.value, status=task.status.value,
                      materiality_inr=task.materiality_inr, created_at=task.created_at)
        self.s.add(row)
        self.s.flush()
        self.s.refresh(row)
        return mappers.task_to_domain(row)

    def get(self, task_id: int) -> Task | None:
        row = self.s.scalars(walled(select(TaskRow).where(TaskRow.id == task_id), self.viewer,
                                    TaskRow.deal_id, include_unattached=True)).first()
        return mappers.task_to_domain(row) if row else None

    def update(self, task: Task) -> Task:
        row = self.s.get(TaskRow, task.id)
        row.status = task.status.value
        self.s.flush()
        self.s.refresh(row)
        return mappers.task_to_domain(row)


class SqlHandoffRepository:
    def __init__(self, session: Session, viewer: Viewer):
        self.s, self.viewer = session, check_viewer(viewer)

    def _select(self):
        stmt = (select(HandoffRow, TaskRow.job_id, TaskRow.task_type)
                .join(TaskRow, TaskRow.id == HandoffRow.task_id))
        return walled(stmt, self.viewer, HandoffRow.deal_id, include_unattached=True)

    def _many(self, stmt) -> list[Handoff]:
        return [mappers.handoff_to_domain(r, job_id, task_type)
                for r, job_id, task_type in self.s.execute(stmt).all()]

    def add(self, handoff: Handoff) -> Handoff:
        row = HandoffRow(
            task_id=handoff.task_id, deal_id=handoff.deal_id,
            direction=handoff.direction.value, trigger=handoff.trigger.value,
            context_package=handoff.context_package, directive=handoff.directive,
            status=handoff.status.value, auto_escalate_at=handoff.auto_escalate_at,
            created_at=handoff.created_at, resolved_by=handoff.resolved_by,
            resolved_at=handoff.resolved_at)
        self.s.add(row)
        self.s.flush()
        self.s.refresh(row)
        return mappers.handoff_to_domain(row, handoff.job_id, handoff.task_type)

    def get(self, handoff_id: int) -> Handoff | None:
        found = self._many(self._select().where(HandoffRow.id == handoff_id))
        return found[0] if found else None

    def update(self, handoff: Handoff) -> Handoff:
        row = self.s.get(HandoffRow, handoff.id)
        row.status = handoff.status.value
        row.directive = handoff.directive
        row.resolved_by, row.resolved_at = handoff.resolved_by, handoff.resolved_at
        self.s.flush()
        self.s.refresh(row)
        return mappers.handoff_to_domain(row, handoff.job_id, handoff.task_type)

    def list_all(self, resolved: bool | None = None) -> list[Handoff]:
        stmt = self._select()
        if resolved is True:
            stmt = stmt.where(HandoffRow.status == HandoffStatus.RESOLVED.value)
        elif resolved is False:
            stmt = stmt.where(HandoffRow.status != HandoffStatus.RESOLVED.value)
        return self._many(stmt.order_by(HandoffRow.id.desc()))

    def count_waiting(self) -> int:
        stmt = walled(select(func.count(HandoffRow.id))
                      .where(HandoffRow.status != HandoffStatus.RESOLVED.value),
                      self.viewer, HandoffRow.deal_id, include_unattached=True)
        return self.s.scalar(stmt) or 0

    def list_overdue(self, now: datetime) -> list[Handoff]:
        return self._many(self._select().where(
            HandoffRow.status == HandoffStatus.OPEN.value,
            HandoffRow.auto_escalate_at.is_not(None),
            HandoffRow.auto_escalate_at <= now))


class SqlAgentRunRepository:
    def __init__(self, session: Session, viewer: Viewer):
        self.s, self.viewer = session, check_viewer(viewer)

    def add(self, run: AgentRun) -> AgentRun:
        row = AgentRunRow(
            job_id=run.job_id, deal_id=run.deal_id, task_id=run.task_id,
            archetype=run.archetype, model_id=run.model_id, model_version=run.model_version,
            prompt_template_id=run.prompt_template_id, prompt_hash=run.prompt_hash,
            input_digest=run.input_digest, output=run.output, confidence=run.confidence,
            tokens_in=run.tokens_in, tokens_out=run.tokens_out, cost_inr=run.cost_inr,
            latency_ms=run.latency_ms, started_at=run.started_at,
            completed_at=run.completed_at, tool_calls=run.tool_calls)
        self.s.add(row)
        self.s.flush()
        self.s.refresh(row)
        return mappers.agent_run_to_domain(row)

    def get(self, run_id: int) -> AgentRun | None:
        row = self.s.scalars(walled(select(AgentRunRow).where(AgentRunRow.id == run_id),
                                    self.viewer, AgentRunRow.deal_id,
                                    include_unattached=True)).first()
        return mappers.agent_run_to_domain(row) if row else None

    def list_for(self, deal_id: int | None = None, limit: int = 200) -> list[AgentRun]:
        stmt = walled(select(AgentRunRow), self.viewer, AgentRunRow.deal_id,
                      include_unattached=True)
        if deal_id is not None:
            stmt = stmt.where(AgentRunRow.deal_id == deal_id)
        rows = self.s.scalars(stmt.order_by(AgentRunRow.id.desc()).limit(limit)).all()
        return [mappers.agent_run_to_domain(r) for r in rows]


class SqlAuditRepository:
    """Append-only by design - no update or delete method exists."""

    def __init__(self, session: Session, viewer: Viewer):
        self.s, self.viewer = session, check_viewer(viewer)

    def append(self, entry: AuditEntry) -> AuditEntry:
        # The lock keeps two threads (API + worker) from reading the same prev_hash. SQLite
        # allows one writer at a time, so a loser fails instead of forking the chain.
        with _AUDIT_LOCK:
            prev = self.s.scalars(select(AuditRow.row_hash)
                                  .order_by(AuditRow.id.desc()).limit(1)).first() or GENESIS_HASH
            row = AuditRow(job_id=entry.job_id, deal_id=entry.deal_id, actor=entry.actor,
                           action=entry.action, payload=entry.payload,
                           created_at=entry.created_at, prev_hash=prev,
                           row_hash=compute_row_hash(prev, entry))
            self.s.add(row)
            self.s.flush()
        self.s.refresh(row)
        return mappers.audit_to_domain(row)

    def list_recent(self, limit: int = 100) -> list[AuditEntry]:
        stmt = walled(select(AuditRow), self.viewer, AuditRow.deal_id, include_unattached=True)
        rows = self.s.scalars(stmt.order_by(AuditRow.id.desc()).limit(limit)).all()
        return [mappers.audit_to_domain(r) for r in rows]

    def count_by_action(self, action: str) -> int:
        stmt = walled(select(func.count(AuditRow.id)).where(AuditRow.action == action),
                      self.viewer, AuditRow.deal_id, include_unattached=True)
        return self.s.scalar(stmt) or 0


class SqlUserRepository:
    def __init__(self, session: Session):
        self.s = session

    def get_by_username(self, username: str) -> User | None:
        row = self.s.scalars(select(UserRow).where(UserRow.username == username)).first()
        return mappers.user_to_domain(row) if row else None

    def get(self, user_id: int) -> User | None:
        row = self.s.get(UserRow, user_id)
        return mappers.user_to_domain(row) if row else None

    def list_all(self) -> list[User]:
        return [mappers.user_to_domain(r)
                for r in self.s.scalars(select(UserRow).order_by(UserRow.id))]

    def add(self, user: User) -> User:
        row = UserRow(username=user.username, password_hash=user.password_hash,
                      role=user.role.value, active=user.active)
        self.s.add(row)
        self.s.flush()
        self.s.refresh(row)
        return mappers.user_to_domain(row)

    def update(self, user: User) -> User:
        row = self.s.get(UserRow, user.id)
        row.role, row.active = user.role.value, user.active
        self.s.flush()
        self.s.refresh(row)
        return mappers.user_to_domain(row)

    def usernames_with_role(self, role: Role) -> list[str]:
        return list(self.s.scalars(select(UserRow.username).where(
            UserRow.role == role.value, UserRow.active.is_(True)).order_by(UserRow.id)))
