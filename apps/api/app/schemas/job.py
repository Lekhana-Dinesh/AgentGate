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
    locked_by: str | None
    locked_at: datetime | None
    lease_expires_at: datetime | None
    dead_letter_reason: str | None
    dead_lettered: bool
    can_retry: bool
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


def _manual_retry_supported(job_type: JobType) -> bool:
    return job_type in {
        JobType.APPROVAL_NOTIFICATION_SLACK,
        JobType.AUDIT_EXPORT_PLACEHOLDER,
        JobType.AUDIT_INTEGRITY_CHECKPOINT_PLACEHOLDER,
        JobType.RETENTION_PURGE_PLACEHOLDER,
        JobType.AUDIT_INTEGRITY_VERIFY_PLACEHOLDER,
        JobType.CONNECTOR_HEALTH_CHECK_PLACEHOLDER,
    }


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
        locked_by=job.locked_by,
        locked_at=job.locked_at,
        lease_expires_at=job.lease_expires_at,
        dead_letter_reason=job.dead_letter_reason,
        dead_lettered=bool(job.dead_letter_reason),
        can_retry=(
            job.status in {JobStatus.FAILED, JobStatus.RETRY_EXHAUSTED}
            and _manual_retry_supported(job.job_type)
        ),
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
        locked_by=job.locked_by,
        locked_at=job.locked_at,
        lease_expires_at=job.lease_expires_at,
        dead_letter_reason=job.dead_letter_reason,
        dead_lettered=bool(job.dead_letter_reason),
        can_retry=(
            job.status in {JobStatus.FAILED, JobStatus.RETRY_EXHAUSTED}
            and _manual_retry_supported(job.job_type)
        ),
        created_at=job.created_at,
        updated_at=job.updated_at,
        completed_at=job.completed_at,
    )
