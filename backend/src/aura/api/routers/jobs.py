from fastapi import APIRouter, Depends, Header, HTTPException, Response, status

from aura.api.deps import (current_user, get_audit, get_deals, get_documents, get_events,
                           get_idempotency, get_jobs, get_parties, get_segments, get_store)
from aura.api.schemas.dto import DeadLetterResponse, JobResponse, SubmitJobRequest
from aura.core.domain.user import User
from aura.core.services.segment_reliability import list_dead_letter, retry_job
from aura.core.services.submit_job import submit_job_idempotent

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


def _to_response(job) -> JobResponse:
    return JobResponse(id=job.id, status=job.status.value, inputs=job.inputs,
                       result=job.result, deal_id=job.deal_id, created_at=job.created_at,
                       created_by=job.created_by)


@router.post("", response_model=JobResponse, status_code=status.HTTP_202_ACCEPTED)
def create_job(body: SubmitJobRequest, response: Response,
               idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
               user: User = Depends(current_user),
               jobs=Depends(get_jobs), segments=Depends(get_segments),
               audit=Depends(get_audit), events=Depends(get_events),
               deals=Depends(get_deals), documents=Depends(get_documents),
               parties=Depends(get_parties), store=Depends(get_store),
               idempotency=Depends(get_idempotency)):
    """An optional Idempotency-Key header makes the call safe to repeat: the same key and
    body within 24 hours return the original job (200, header Idempotent-Replayed: true)
    instead of a new one; the same key with a different body is a 409."""
    job, replayed = submit_job_idempotent(
        idempotency_key, idempotency, inputs=body.inputs, deal_id=body.deal_id,
        actor=user.username, jobs=jobs, actor_role=user.role, segments=segments,
        audit=audit, events=events, deals=deals, documents=documents, parties=parties,
        store=store)
    if replayed:
        response.status_code = status.HTTP_200_OK
        response.headers["Idempotent-Replayed"] = "true"
    return _to_response(job)


@router.get("", response_model=list[JobResponse])
def list_jobs(user: User = Depends(current_user), jobs=Depends(get_jobs)):
    return [_to_response(j) for j in jobs.list_recent()]


@router.get("/dead-letter", response_model=list[DeadLetterResponse])
def dead_letter(user: User = Depends(current_user), jobs=Depends(get_jobs),
                segments=Depends(get_segments)):
    """Jobs whose segment exhausted its retries (dealmaker and analyst; wall-filtered)."""
    return [DeadLetterResponse(job=_to_response(job), segment_id=seg.id, seq=seg.seq,
                               status=seg.status.value, attempts=seg.attempts,
                               last_error=seg.last_error, claimed_by=seg.claimed_by,
                               ended_at=seg.ended_at)
            for seg, job in list_dead_letter(user.role, jobs, segments)]


@router.get("/{job_id}", response_model=JobResponse)
def get_job(job_id: int, user: User = Depends(current_user), jobs=Depends(get_jobs)):
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    return _to_response(job)


@router.post("/{job_id}/retry", response_model=JobResponse,
             status_code=status.HTTP_202_ACCEPTED)
def retry(job_id: int, user: User = Depends(current_user), jobs=Depends(get_jobs),
          segments=Depends(get_segments), audit=Depends(get_audit),
          events=Depends(get_events)):
    """Queue a dead-lettered or failed job's last segment again (audited
    'segment_retried'). 409 when there is nothing to retry."""
    return _to_response(retry_job(job_id, user.username, user.role, jobs, segments, audit,
                                  events))
