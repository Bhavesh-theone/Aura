from fastapi import APIRouter, Depends, HTTPException, status

from aura.api.deps import (current_user, get_audit, get_deals, get_documents, get_events,
                           get_jobs, get_parties, get_segments, get_store)
from aura.api.schemas.dto import JobResponse, SubmitJobRequest
from aura.core.domain.user import User
from aura.core.services.submit_job import submit_job

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


def _to_response(job) -> JobResponse:
    return JobResponse(id=job.id, status=job.status.value, inputs=job.inputs,
                       result=job.result, deal_id=job.deal_id, created_at=job.created_at,
                       created_by=job.created_by)


@router.post("", response_model=JobResponse, status_code=status.HTTP_202_ACCEPTED)
def create_job(body: SubmitJobRequest, user: User = Depends(current_user),
               jobs=Depends(get_jobs), segments=Depends(get_segments),
               audit=Depends(get_audit), events=Depends(get_events),
               deals=Depends(get_deals), documents=Depends(get_documents),
               parties=Depends(get_parties), store=Depends(get_store)):
    job = submit_job(inputs=body.inputs, deal_id=body.deal_id, actor=user.username,
                     actor_role=user.role, jobs=jobs, segments=segments, audit=audit,
                     events=events, deals=deals, documents=documents, parties=parties,
                     store=store)
    return _to_response(job)


@router.get("", response_model=list[JobResponse])
def list_jobs(user: User = Depends(current_user), jobs=Depends(get_jobs)):
    return [_to_response(j) for j in jobs.list_recent()]


@router.get("/{job_id}", response_model=JobResponse)
def get_job(job_id: int, user: User = Depends(current_user), jobs=Depends(get_jobs)):
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    return _to_response(job)
