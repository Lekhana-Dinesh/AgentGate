from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.core.enums import AuditActorType, UserRole
from app.db.session import get_db
from app.schemas.audit_export import (
    AuditExportConfigResponse,
    AuditExportCreate,
    AuditExportRunRequest,
    AuditExportRunResponse,
    AuditExportStatusResponse,
    AuditExportUpdate,
)
from app.schemas.job import serialize_job
from app.services.audit_export_service import AuditExportService
from app.services.rate_limit_service import get_rate_limiter, get_rate_limit_settings

router = APIRouter()
audit_export_service = AuditExportService()


@router.get("", response_model=list[AuditExportConfigResponse])
def list_audit_export_configs(
    current_user=Depends(
        require_roles(
            UserRole.OWNER,
            UserRole.ADMIN,
            UserRole.SECURITY_REVIEWER,
        )
    ),
    db: Session = Depends(get_db),
) -> list[AuditExportConfigResponse]:
    return audit_export_service.list_configs(db, tenant_id=current_user.tenant_id)


@router.post("", response_model=AuditExportConfigResponse, status_code=status.HTTP_201_CREATED)
def create_audit_export_config(
    payload: AuditExportCreate,
    current_user=Depends(
        require_roles(
            UserRole.OWNER,
            UserRole.ADMIN,
            UserRole.SECURITY_REVIEWER,
        )
    ),
    db: Session = Depends(get_db),
) -> AuditExportConfigResponse:
    config = audit_export_service.create_config(
        db,
        tenant_id=current_user.tenant_id,
        payload=payload,
        current_user=current_user,
    )
    db.commit()
    return audit_export_service.get_config_response(
        db,
        tenant_id=current_user.tenant_id,
        config_id=config.id,
    )


@router.patch("/{config_id}", response_model=AuditExportConfigResponse)
def update_audit_export_config(
    config_id: str,
    payload: AuditExportUpdate,
    current_user=Depends(
        require_roles(
            UserRole.OWNER,
            UserRole.ADMIN,
            UserRole.SECURITY_REVIEWER,
        )
    ),
    db: Session = Depends(get_db),
) -> AuditExportConfigResponse:
    config = audit_export_service.update_config(
        db,
        tenant_id=current_user.tenant_id,
        config_id=config_id,
        payload=payload,
        current_user=current_user,
    )
    db.commit()
    return audit_export_service.get_config_response(
        db,
        tenant_id=current_user.tenant_id,
        config_id=config.id,
    )


@router.post("/{config_id}/run", response_model=AuditExportRunResponse)
def run_audit_export(
    config_id: str,
    payload: AuditExportRunRequest,
    request: Request,
    current_user=Depends(
        require_roles(
            UserRole.OWNER,
            UserRole.ADMIN,
            UserRole.SECURITY_REVIEWER,
        )
    ),
    db: Session = Depends(get_db),
) -> AuditExportRunResponse:
    get_rate_limiter().enforce(
        scope="audit_export",
        key_parts=[
            request.client.host if request.client else None,
            current_user.tenant_id,
            current_user.id,
            config_id,
        ],
        settings=get_rate_limit_settings("audit_export"),
        db=db,
        tenant_id=current_user.tenant_id,
        actor_type=AuditActorType.USER,
        actor_id=current_user.id,
        ip_address=request.client.host if request.client else None,
        audit_on_exhaustion=True,
        resource_type="audit_export_config",
        resource_id=config_id,
        metadata={"endpoint": "audit_export.run"},
    )
    config = audit_export_service.get_config_or_raise(
        db,
        tenant_id=current_user.tenant_id,
        config_id=config_id,
    )
    job = audit_export_service.enqueue_run(
        db,
        config=config,
        requested_by=current_user,
        dry_run=payload.dry_run,
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    audit_export_service.job_service.dispatch_after_commit(
        db,
        job_id=job.id,
        raise_on_error=True,
    )
    refreshed_job = audit_export_service.job_service.get_job(
        db,
        job_id=job.id,
        tenant_id=current_user.tenant_id,
    ) or job
    return AuditExportRunResponse(
        dry_run=payload.dry_run,
        dispatch_mode="inline" if audit_export_service.job_service.is_inline_dispatch() else "worker",
        job=serialize_job(refreshed_job),
        result=audit_export_service.get_job_result(
            db,
            job_id=job.id,
            tenant_id=current_user.tenant_id,
        ),
    )


@router.get("/{config_id}/status", response_model=AuditExportStatusResponse)
def get_audit_export_status(
    config_id: str,
    current_user=Depends(
        require_roles(
            UserRole.OWNER,
            UserRole.ADMIN,
            UserRole.SECURITY_REVIEWER,
        )
    ),
    db: Session = Depends(get_db),
) -> AuditExportStatusResponse:
    return audit_export_service.get_status(
        db,
        tenant_id=current_user.tenant_id,
        config_id=config_id,
    )
