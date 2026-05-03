from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from app.core.enums import JobStatus, JobType
from app.schemas.common import ORMModel
from app.services.payload_service import PayloadService


class JobSummary(ORMModel):
    id: str
    job_type: JobType
    status: JobStatus
    attempts: int
    max_attempts: int
    last_error: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class JobResponse(JobSummary):
    tenant_id: str
    idempotency_key: str
    next_run_at: datetime
    payload: dict


class ApprovalExecutionStatus(BaseModel):
    status: str
    job: JobSummary | None = None
    message: str | None = None


def serialize_job(job) -> JobResponse:
    payload_service = PayloadService()
    return JobResponse(
        id=job.id,
        tenant_id=job.tenant_id,
        job_type=job.job_type,
        status=job.status,
        idempotency_key=job.idempotency_key,
        payload=payload_service.sanitize_payload(job.payload),
        attempts=job.attempts,
        max_attempts=job.max_attempts,
        next_run_at=job.next_run_at,
        last_error=job.last_error,
        created_at=job.created_at,
        updated_at=job.updated_at,
        completed_at=job.completed_at,
    )


def serialize_job_summary(job) -> JobSummary:
    return JobSummary(
        id=job.id,
        job_type=job.job_type,
        status=job.status,
        attempts=job.attempts,
        max_attempts=job.max_attempts,
        last_error=job.last_error,
        created_at=job.created_at,
        updated_at=job.updated_at,
        completed_at=job.completed_at,
    )
