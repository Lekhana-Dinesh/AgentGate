from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.core.enums import AuditActorType, UserRole
from app.db.session import get_db
from app.schemas.job import serialize_job
from app.schemas.retention import (
    RetentionPurgeRequest,
    RetentionPurgeResponse,
    RetentionStatusResponse,
    serialize_retention_result,
    serialize_retention_status,
)
from app.services.rate_limit_service import get_rate_limiter, get_rate_limit_settings
from app.services.retention_service import RetentionPurgeFilters, RetentionService

router = APIRouter()
retention_service = RetentionService()


@router.get("/status", response_model=RetentionStatusResponse)
def get_retention_status(
    current_user=Depends(
        require_roles(
            UserRole.OWNER,
            UserRole.ADMIN,
            UserRole.SECURITY_REVIEWER,
        )
    ),
    db: Session = Depends(get_db),
) -> RetentionStatusResponse:
    summary = retention_service.get_status_summary(
        db,
        tenant_id=current_user.tenant_id,
    )
    return serialize_retention_status(summary)


@router.post("/purge", response_model=RetentionPurgeResponse)
def enqueue_retention_purge(
    payload: RetentionPurgeRequest,
    request: Request,
    current_user=Depends(
        require_roles(
            UserRole.OWNER,
            UserRole.ADMIN,
            UserRole.SECURITY_REVIEWER,
        )
    ),
    db: Session = Depends(get_db),
) -> RetentionPurgeResponse:
    get_rate_limiter().enforce(
        scope="retention",
        key_parts=[
            request.client.host if request.client else None,
            current_user.tenant_id,
            current_user.id,
        ],
        settings=get_rate_limit_settings("retention"),
        db=db,
        tenant_id=current_user.tenant_id,
        actor_type=AuditActorType.USER,
        actor_id=current_user.id,
        ip_address=request.client.host if request.client else None,
        audit_on_exhaustion=True,
        resource_type="tenant",
        resource_id=current_user.tenant_id,
        metadata={"endpoint": "retention.purge"},
    )
    filters = RetentionPurgeFilters(
        retention_classes=[item.value for item in payload.retention_classes],
        tool_name=payload.tool_name,
        tool_call_ids=payload.tool_call_ids,
        limit=payload.limit,
    )
    job = retention_service.enqueue_purge_job(
        db,
        tenant_id=current_user.tenant_id,
        requested_by=current_user,
        dry_run=payload.dry_run,
        filters=filters,
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    retention_service.job_service.dispatch_after_commit(
        db,
        job_id=job.id,
        raise_on_error=True,
    )
    refreshed_job = retention_service.job_service.get_job(db, job_id=job.id, tenant_id=current_user.tenant_id) or job
    return RetentionPurgeResponse(
        dry_run=payload.dry_run,
        dispatch_mode="inline" if retention_service.job_service.is_inline_dispatch() else "worker",
        job=serialize_job(refreshed_job),
        result=serialize_retention_result(retention_service.get_job_result(db, job_id=job.id, tenant_id=current_user.tenant_id)),
    )
