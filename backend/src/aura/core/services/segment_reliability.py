"""What happens to a segment when things go wrong: retries with backoff, dead letters,
recovery of segments orphaned by a crash, the daily model budget, and manual retry.

Every transition here is audited (with the job's deal, so the trail and the metrics stay
behind the deal's wall) and keeps the job's status consistent with its segment.
"""
from datetime import datetime, time, timedelta

from aura.core.clock import utcnow
from aura.core.domain.audit import AuditEntry
from aura.core.domain.enums import JobStatus, Role, SegmentStatus
from aura.core.domain.errors import Conflict, NotFound
from aura.core.domain.job import Job
from aura.core.domain.segment import Segment
from aura.core.policy.rbac_policy import Capability, require
from aura.core.policy.retry_policy import RetryPolicy, error_text, is_transient
from aura.core.ports.events import EventPublisher
from aura.core.ports.orchestrator import BudgetExceeded
from aura.core.ports.repositories import AuditRepository, JobRepository, SegmentRepository

RETRYABLE = (SegmentStatus.DEAD_LETTER, SegmentStatus.FAILED)


def _audit(audit: AuditRepository, job: Job, actor: str, action: str, payload: dict,
           now: datetime) -> None:
    audit.append(AuditEntry(id=None, job_id=job.id, deal_id=job.deal_id, actor=actor,
                            action=action, payload=payload, created_at=now))


def _requeue(segment: Segment, job: Job, run_at: datetime | None, segments: SegmentRepository,
             jobs: JobRepository) -> None:
    segment.status = SegmentStatus.QUEUED
    segment.not_before = run_at
    segment.context_out = None
    segment.claimed_by = segment.claimed_at = None
    segments.update(segment)
    job.status = JobStatus.PENDING
    jobs.update(job)


def dead_letter(segment: Segment, job: Job, error: str, segments: SegmentRepository,
                jobs: JobRepository, audit: AuditRepository, events: EventPublisher,
                now: datetime, reason: str) -> None:
    segment.status = SegmentStatus.DEAD_LETTER
    segment.last_error = error
    segment.ended_at = now
    segments.update(segment)
    job.status = JobStatus.FAILED
    jobs.update(job)
    _audit(audit, job, "system", "segment_dead_lettered",
           {"segment_id": segment.id, "attempts": segment.attempts, "error": error,
            "reason": reason}, now)
    events.publish("segment_dead_lettered", {"job_id": job.id, "deal_id": job.deal_id,
                                             "segment_id": segment.id})
    events.publish("job_failed", {"job_id": job.id, "deal_id": job.deal_id})


def handle_segment_failure(segment: Segment, job: Job, exc: BaseException,
                           policy: RetryPolicy, segments: SegmentRepository,
                           jobs: JobRepository, audit: AuditRepository,
                           events: EventPublisher, now: datetime | None = None) -> str:
    """Decide and record what a failed attempt leads to. Returns 'retry', 'dead_letter' or
    'failed'. The caller has already rolled back whatever the attempt wrote."""
    now = now or utcnow()
    error = error_text(exc)
    segment.last_error = error
    if is_transient(exc):
        if policy.can_retry(segment.attempts):
            run_at = policy.next_run_at(now, segment.attempts)
            _requeue(segment, job, run_at, segments, jobs)
            _audit(audit, job, "system", "segment_retry_scheduled",
                   {"segment_id": segment.id, "attempts": segment.attempts, "error": error,
                    "not_before": run_at.isoformat()}, now)
            events.publish("job_retrying", {"job_id": job.id, "deal_id": job.deal_id,
                                            "segment_id": segment.id})
            return "retry"
        dead_letter(segment, job, error, segments, jobs, audit, events, now,
                    reason="max_attempts")
        return "dead_letter"

    segment.status = SegmentStatus.FAILED
    segment.ended_at = now
    segments.update(segment)
    job.status = JobStatus.FAILED
    jobs.update(job)
    payload = {"segment_id": segment.id, "error": str(exc), "permanent": True}
    if isinstance(exc, BudgetExceeded):
        payload["reason"] = "budget_exceeded"
    _audit(audit, job, "system", "segment_failed", payload, now)
    events.publish("job_failed", {"job_id": job.id, "deal_id": job.deal_id})
    return "failed"


def recover_stale_segments(segments: SegmentRepository, jobs: JobRepository,
                           audit: AuditRepository, events: EventPublisher,
                           policy: RetryPolicy, now: datetime | None = None) -> int:
    """RUNNING segments whose claim is older than the lease were orphaned (the worker died
    mid-run). Requeue each one that still has attempts left; dead-letter the rest."""
    now = now or utcnow()
    stale = segments.list_stale_running(now - timedelta(seconds=policy.lease_seconds))
    for segment in stale:
        job = jobs.get(segment.job_id)
        if job is None:
            continue
        error = (f"Lease expired: claimed by {segment.claimed_by or 'unknown'} at "
                 f"{segment.claimed_at.isoformat() if segment.claimed_at else 'unknown'} and "
                 "never finished")
        if policy.can_retry(segment.attempts):
            segment.last_error = error
            _requeue(segment, job, None, segments, jobs)
            _audit(audit, job, "system", "segment_recovered",
                   {"segment_id": segment.id, "attempts": segment.attempts, "error": error},
                   now)
            events.publish("job_retrying", {"job_id": job.id, "deal_id": job.deal_id,
                                            "segment_id": segment.id})
        else:
            dead_letter(segment, job, error, segments, jobs, audit, events, now,
                        reason="lease_expired")
    return len(stale)


def next_utc_day(now: datetime) -> datetime:
    return datetime.combine(now.date() + timedelta(days=1), time(0, 0), tzinfo=now.tzinfo)


def start_of_utc_day(now: datetime) -> datetime:
    return datetime.combine(now.date(), time(0, 0), tzinfo=now.tzinfo)


def defer_for_budget(segment: Segment, job: Job, used: int, limit: int,
                     segments: SegmentRepository, jobs: JobRepository,
                     audit: AuditRepository, events: EventPublisher,
                     now: datetime | None = None) -> datetime:
    """The daily model budget is spent: put the just-claimed segment back until tomorrow.
    The claim does not count as an attempt."""
    now = now or utcnow()
    run_at = next_utc_day(now)
    segment.attempts = max(0, segment.attempts - 1)
    _requeue(segment, job, run_at, segments, jobs)
    _audit(audit, job, "system", "budget_deferred",
           {"segment_id": segment.id, "llm_calls_today": used, "daily_limit": limit,
            "not_before": run_at.isoformat()}, now)
    events.publish("job_deferred", {"job_id": job.id, "deal_id": job.deal_id,
                                    "segment_id": segment.id})
    return run_at


def list_dead_letter(actor_role: Role, jobs: JobRepository,
                     segments: SegmentRepository) -> list[tuple[Segment, Job]]:
    """Dead-lettered segments with their jobs, for the people who run agent jobs. `jobs` is
    the viewer's: a segment whose job is behind a wall they are not on is left out."""
    require(actor_role, Capability.SUBMIT_JOB, "see dead-lettered jobs")
    found = []

    for segment in segments.list_by_status(SegmentStatus.DEAD_LETTER):
        job = jobs.get(segment.job_id)
        if job is not None:
            found.append((segment, job))
    return found


def retry_job(job_id: int, actor: str, actor_role: Role, jobs: JobRepository,
              segments: SegmentRepository, audit: AuditRepository, events: EventPublisher,
              now: datetime | None = None) -> Job:
    """A person sends a dead-lettered (or failed) job round again: its last segment is
    queued afresh with a clean attempt count."""
    require(actor_role, Capability.SUBMIT_JOB, "retry agent jobs")
    now = now or utcnow()
    job = jobs.get(job_id)
    if job is None:
        raise NotFound("Job not found")
    history = segments.list_for_job(job_id)
    segment = history[-1] if history else None
    if segment is None or segment.status not in RETRYABLE:
        raise Conflict(f"Job {job_id} has no failed or dead-lettered segment to retry")
    previous = segment.status
    previous_error = segment.last_error
    segment.attempts = 0
    segment.last_error = None
    segment.ended_at = None
    _requeue(segment, job, None, segments, jobs)
    _audit(audit, job, actor, "segment_retried",
           {"segment_id": segment.id, "previous_status": previous.value,
            "previous_error": previous_error}, now)
    events.publish("job_retried", {"job_id": job.id, "deal_id": job.deal_id,
                                   "segment_id": segment.id})
    return job
