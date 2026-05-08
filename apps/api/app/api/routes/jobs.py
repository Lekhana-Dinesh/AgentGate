from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.core.enums import AuditActorType, JobStatus, JobType, UserRole
from app.core.errors import AppError
from app.db.session import get_db
from app.schemas.job import JobResponse, serialize_job
from app.services.job_service import JobService
from app.services.rate_limit_service import get_rate_limiter, get_rate_limit_settings

router = APIRouter()
job_service = JobService()


@router.get("", response_model=list[JobResponse])
def list_jobs(
    status: JobStatus | None = Query(default=None),
    job_type: JobType | None = Query(default=None),
    dead_lettered: bool | None = Query(default=None),
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
        dead_lettered=dead_lettered,
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


@router.post("/{job_id}/retry", response_model=JobResponse)
def retry_job(
    job_id: str,
    request: Request,
    current_user=Depends(
        require_roles(
            UserRole.OWNER,
            UserRole.ADMIN,
            UserRole.SECURITY_REVIEWER,
        )
    ),
    db: Session = Depends(get_db),
) -> JobResponse:
    get_rate_limiter().enforce(
        scope="jobs_retry",
        key_parts=[
            request.client.host if request.client else None,
            current_user.tenant_id,
            current_user.id,
            job_id,
        ],
        settings=get_rate_limit_settings("jobs_retry"),
        db=db,
        tenant_id=current_user.tenant_id,
        actor_type=AuditActorType.USER,
        actor_id=current_user.id,
        ip_address=request.client.host if request.client else None,
        audit_on_exhaustion=True,
        resource_type="job",
        resource_id=job_id,
        metadata={"endpoint": "jobs.retry"},
    )
    job = job_service.retry_job(
        db,
        job_id=job_id,
        tenant_id=current_user.tenant_id,
        actor_id=current_user.id,
        ip_address=request.client.host if request.client else None,
    )
    job = job_service.dispatch_after_commit(db, job_id=job.id, raise_on_error=False) or job
    return serialize_job(job)
