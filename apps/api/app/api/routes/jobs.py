from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.core.enums import JobStatus, JobType, UserRole
from app.core.errors import AppError
from app.db.session import get_db
from app.schemas.job import JobResponse, serialize_job
from app.services.job_service import JobService

router = APIRouter()
job_service = JobService()


@router.get("", response_model=list[JobResponse])
def list_jobs(
    status: JobStatus | None = Query(default=None),
    job_type: JobType | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    current_user=Depends(
        require_roles(
            UserRole.OWNER,
            UserRole.ADMIN,
            UserRole.SECURITY_REVIEWER,
            UserRole.DEVELOPER,
        )
    ),
    db: Session = Depends(get_db),
) -> list[JobResponse]:
    jobs = job_service.list_jobs(
        db,
        tenant_id=current_user.tenant_id,
        status=status,
        job_type=job_type,
        limit=limit,
        offset=offset,
    )
    return [serialize_job(job) for job in jobs]


@router.get("/{job_id}", response_model=JobResponse)
def get_job(
    job_id: str,
    current_user=Depends(
        require_roles(
            UserRole.OWNER,
            UserRole.ADMIN,
            UserRole.SECURITY_REVIEWER,
            UserRole.DEVELOPER,
        )
    ),
    db: Session = Depends(get_db),
) -> JobResponse:
    job = job_service.get_job(db, job_id=job_id, tenant_id=current_user.tenant_id)
    if not job:
        raise AppError("Job not found.", status_code=404, code="job_not_found")
    return serialize_job(job)
