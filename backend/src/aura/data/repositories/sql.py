"""Job, segment, audit, task, handoff, agent-run and user repositories.

None of these commit: they flush, and the unit of work that owns the session commits.
Deal-scoped ones take a `viewer` (see aura.data.walls) and only ever see deals behind walls
that viewer is on.
"""
import sqlite3
import threading
from dataclasses import replace
from datetime import datetime

from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from aura.core.clock import utcnow
from aura.core.tracing import current_trace
from aura.core.domain.agent_run import AgentRun
from aura.core.domain.errors import Conflict
from aura.core.domain.job import IdempotencyRecord
from aura.core.domain.audit import GENESIS_HASH, AuditEntry, compute_row_hash
from aura.core.domain.enums import HandoffStatus, Role, SegmentStatus
from aura.core.domain.handoff import Handoff, Task
from aura.core.domain.job import Job
from aura.core.domain.segment import Segment
from aura.core.domain.user import User
from aura.data import mappers
from aura.data.models.tables import (AgentRunRow, AuditRow, HandoffRow, IdempotencyKeyRow,
                                     JobRow, SegmentRow, TaskRow, UserRow)
from aura.data.walls import Viewer, check_viewer, walled

_AUDIT_LOCK = threading.Lock()
# UPDATE ... RETURNING needs SQLite 3.35 (other databases have it).
_HAS_RETURNING = sqlite3.sqlite_version_info >= (3, 35)


def _locked(exc: OperationalError) -> bool:
    return "locked" in str(exc).lower() or "busy" in str(exc).lower()


class SqlJobRepository:
    def __init__(self, session: Session, viewer: Viewer):
        self.s, self.viewer = session, check_viewer(viewer)

    def add(self, job: Job) -> Job:
        row = JobRow(status=job.status.value, inputs=job.inputs, result=job.result,
                     deal_id=job.deal_id, created_at=job.created_at,
                     created_by=job.created_by, trace_id=job.trace_id, span_id=job.span_id)
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
        row.claimed_by, row.claimed_at = segment.claimed_by, segment.claimed_at
        row.attempts, row.not_before = segment.attempts, segment.not_before
        row.last_error = segment.last_error
        self.s.flush()
        self.s.refresh(row)
        return mappers.segment_to_domain(row)

    def _claimable(self, now: datetime):
        return (select(SegmentRow.id)
                .where(SegmentRow.status == SegmentStatus.QUEUED.value,
                       or_(SegmentRow.not_before.is_(None), SegmentRow.not_before <= now))
                .order_by(SegmentRow.id.asc()).limit(1))

    def claim_next_queued(self, worker_id: str = "worker",
                          now: datetime | None = None) -> Segment | None:
        """One conditional UPDATE takes the oldest runnable queued segment, so two workers
        (or threads) can never both claim it: the loser's UPDATE matches no row. Call it
        first in a fresh transaction and commit straight after, so the write lock is held
        for as short a time as possible."""
        now = now or utcnow()
        values = {"status": SegmentStatus.RUNNING.value, "claimed_by": worker_id,
                  "claimed_at": now, "attempts": SegmentRow.attempts + 1}
        if _HAS_RETURNING:
            stmt = (update(SegmentRow)
                    .where(SegmentRow.id == self._claimable(now).scalar_subquery(),
                           SegmentRow.status == SegmentStatus.QUEUED.value)
                    .values(**values).returning(SegmentRow.id)
                    .execution_options(synchronize_session=False))
            claimed_id = self.s.execute(stmt).scalar_one_or_none()
        else:  # SQLite < 3.35: pick, then update only if it is still queued
            claimed_id = None
            candidate = self.s.scalar(self._claimable(now))
            if candidate is not None:
                result = self.s.execute(
                    update(SegmentRow)
                    .where(SegmentRow.id == candidate,
                           SegmentRow.status == SegmentStatus.QUEUED.value)
                    .values(**values).execution_options(synchronize_session=False))
                claimed_id = candidate if result.rowcount == 1 else None
        if claimed_id is None:
            return None
        row = self.s.get(SegmentRow, claimed_id, populate_existing=True)
        return mappers.segment_to_domain(row)

    def list_for_job(self, job_id: int) -> list[Segment]:
        rows = self.s.scalars(
            select(SegmentRow).where(SegmentRow.job_id == job_id).order_by(SegmentRow.seq)
        ).all()
        return [mappers.segment_to_domain(r) for r in rows]

    def list_stale_running(self, claimed_before: datetime) -> list[Segment]:
        rows = self.s.scalars(
            select(SegmentRow).where(
                SegmentRow.status == SegmentStatus.RUNNING.value,
                or_(SegmentRow.claimed_at.is_(None), SegmentRow.claimed_at < claimed_before))
            .order_by(SegmentRow.id)).all()
        return [mappers.segment_to_domain(r) for r in rows]

    def list_by_status(self, status: SegmentStatus) -> list[Segment]:
        rows = self.s.scalars(select(SegmentRow).where(SegmentRow.status == status.value)
                              .order_by(SegmentRow.id.desc())).all()
        return [mappers.segment_to_domain(r) for r in rows]

    def hold_claim(self, segment_id: int, claimed_by: str | None, attempts: int) -> bool:
        """A no-op UPDATE that only matches while the claim is unchanged. Being a write, it
        takes SQLite's write lock for the rest of the transaction, so a recovery sweep cannot
        requeue the segment between this check and the outcome's commit."""
        owner = SegmentRow.claimed_by.is_(None) if claimed_by is None \
            else SegmentRow.claimed_by == claimed_by
        try:
            result = self.s.execute(
                update(SegmentRow)
                .where(SegmentRow.id == segment_id, owner, SegmentRow.attempts == attempts,
                       SegmentRow.status == SegmentStatus.RUNNING.value)
                .values(claimed_by=SegmentRow.claimed_by)
                .execution_options(synchronize_session=False))
        except OperationalError as exc:
            if _locked(exc):
                return False
            raise
        return result.rowcount == 1


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

    def mark_resolved(self, handoff: Handoff) -> bool:
        """Resolve only while the row is still open or escalated. The UPDATE's WHERE is the
        check, so of two concurrent resolves exactly one matches; the other sees rowcount 0
        (or, while the winner still holds SQLite's write lock, 'database is locked') and
        loses. The viewer's walls still apply: an off-wall handoff never matches."""
        visible = walled(select(HandoffRow.id).where(HandoffRow.id == handoff.id), self.viewer,
                         HandoffRow.deal_id, include_unattached=True)
        stmt = (update(HandoffRow)
                .where(HandoffRow.id.in_(visible.scalar_subquery()),
                       HandoffRow.status.in_([HandoffStatus.OPEN.value,
                                              HandoffStatus.ESCALATED.value]))
                .values(status=HandoffStatus.RESOLVED.value, directive=handoff.directive,
                        resolved_by=handoff.resolved_by, resolved_at=handoff.resolved_at)
                .execution_options(synchronize_session=False))
        try:
            won = self.s.execute(stmt).rowcount == 1
        except OperationalError as exc:
            if _locked(exc):
                return False
            raise
        if won:
            self.s.get(HandoffRow, handoff.id, populate_existing=True)
        return won


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
            completed_at=run.completed_at, tool_calls=run.tool_calls,
            segment_id=run.segment_id, trace_id=run.trace_id, span_id=run.span_id)
        self.s.add(row)
        self.s.flush()
        self.s.refresh(row)
        return mappers.agent_run_to_domain(row)

    def count_since(self, since: datetime) -> int:
        stmt = walled(select(func.count(AgentRunRow.id)).where(AgentRunRow.started_at >= since),
                      self.viewer, AgentRunRow.deal_id, include_unattached=True)
        return self.s.scalar(stmt) or 0

    def link_task(self, segment_id: int, task_id: int) -> int:
        result = self.s.execute(
            update(AgentRunRow)
            .where(AgentRunRow.segment_id == segment_id, AgentRunRow.task_id.is_(None))
            .values(task_id=task_id).execution_options(synchronize_session=False))
        return result.rowcount or 0

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
        # Rows written inside a traced operation carry its trace (before hashing, so the
        # chain covers them).
        trace_id, span_id = current_trace()
        if trace_id is not None and "trace_id" not in (entry.payload or {}):
            entry = replace(entry, payload={**(entry.payload or {}), "trace_id": trace_id,
                                            "span_id": span_id})
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


class SqlIdempotencyRepository:
    """Keys are per user: a key only ever finds the caller's own record."""

    def __init__(self, session: Session):
        self.s = session

    @staticmethod
    def _to_domain(row: IdempotencyKeyRow) -> IdempotencyRecord:
        return IdempotencyRecord(id=row.id, key=row.key, username=row.username,
                                 request_hash=row.request_hash, job_id=row.job_id,
                                 created_at=row.created_at)

    def get(self, key: str, username: str) -> IdempotencyRecord | None:
        row = self.s.scalars(select(IdempotencyKeyRow).where(
            IdempotencyKeyRow.key == key, IdempotencyKeyRow.username == username)).first()
        return self._to_domain(row) if row else None

    def add(self, record: IdempotencyRecord) -> IdempotencyRecord:
        row = IdempotencyKeyRow(key=record.key, username=record.username,
                                request_hash=record.request_hash, job_id=record.job_id,
                                created_at=record.created_at)
        try:
            with self.s.begin_nested():
                self.s.add(row)
                self.s.flush()
        except IntegrityError:
            raise Conflict("This Idempotency-Key is already being used by another "
                           "request") from None
        self.s.refresh(row)
        return self._to_domain(row)

    def delete(self, record_id: int) -> None:
        row = self.s.get(IdempotencyKeyRow, record_id)
        if row is not None:
            self.s.delete(row)
            self.s.flush()


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
