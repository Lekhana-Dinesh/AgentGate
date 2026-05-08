from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.core.enums import AuditActorType, UserRole
from app.core.errors import AppError
from app.db.session import get_db
from app.schemas.audit_integrity import (
    AuditIntegrityBackfillRequest,
    AuditIntegrityBackfillResponse,
    AuditIntegrityCheckpointCreateRequest,
    AuditIntegrityCheckpointResponse,
    AuditIntegrityCheckpointRunResponse,
    AuditIntegrityCheckpointVerifyResponse,
    AuditIntegrityStatusResponse,
    AuditIntegrityVerifyRequest,
    AuditIntegrityVerifyResponse,
)
from app.schemas.job import serialize_job
from app.services.audit_integrity_checkpoint_service import AuditIntegrityCheckpointService
from app.services.audit_integrity_service import AuditIntegrityService, VerificationBounds
from app.services.rate_limit_service import get_rate_limiter, get_rate_limit_settings

router = APIRouter()
audit_integrity_service = AuditIntegrityService()
audit_integrity_checkpoint_service = AuditIntegrityCheckpointService()


@router.get("/status", response_model=AuditIntegrityStatusResponse)
def get_audit_integrity_status(
    current_user=Depends(
        require_roles(
            UserRole.OWNER,
            UserRole.ADMIN,
            UserRole.SECURITY_REVIEWER,
        )
    ),
    db: Session = Depends(get_db),
) -> AuditIntegrityStatusResponse:
    return audit_integrity_service.get_status(db, tenant_id=current_user.tenant_id)


@router.post("/verify", response_model=AuditIntegrityVerifyResponse)
def verify_audit_integrity(
    payload: AuditIntegrityVerifyRequest,
    request: Request,
    current_user=Depends(
        require_roles(
            UserRole.OWNER,
            UserRole.ADMIN,
            UserRole.SECURITY_REVIEWER,
        )
    ),
    db: Session = Depends(get_db),
) -> AuditIntegrityVerifyResponse:
    get_rate_limiter().enforce(
        scope="audit_integrity",
        key_parts=[
            request.client.host if request.client else None,
            current_user.tenant_id,
            current_user.id,
            "verify",
        ],
        settings=get_rate_limit_settings("audit_integrity"),
        db=db,
        tenant_id=current_user.tenant_id,
        actor_type=AuditActorType.USER,
        actor_id=current_user.id,
        ip_address=request.client.host if request.client else None,
        audit_on_exhaustion=True,
        resource_type="tenant",
        resource_id=current_user.tenant_id,
        metadata={"endpoint": "audit_integrity.verify"},
    )
    return audit_integrity_service.verify_chain(
        db,
        tenant_id=current_user.tenant_id,
        bounds=VerificationBounds(
            start_event_id=payload.start_event_id,
            end_event_id=payload.end_event_id,
            start_date=payload.start_date,
            end_date=payload.end_date,
        ),
    )


@router.post("/backfill", response_model=AuditIntegrityBackfillResponse)
def backfill_audit_integrity(
    payload: AuditIntegrityBackfillRequest,
    request: Request,
    current_user=Depends(
        require_roles(
            UserRole.OWNER,
            UserRole.ADMIN,
            UserRole.SECURITY_REVIEWER,
        )
    ),
    db: Session = Depends(get_db),
) -> AuditIntegrityBackfillResponse:
    get_rate_limiter().enforce(
        scope="audit_integrity",
        key_parts=[
            request.client.host if request.client else None,
            current_user.tenant_id,
            current_user.id,
            "backfill",
        ],
        settings=get_rate_limit_settings("audit_integrity"),
        db=db,
        tenant_id=current_user.tenant_id,
        actor_type=AuditActorType.USER,
        actor_id=current_user.id,
        ip_address=request.client.host if request.client else None,
        audit_on_exhaustion=True,
        resource_type="tenant",
        resource_id=current_user.tenant_id,
        metadata={"endpoint": "audit_integrity.backfill"},
    )
    response = audit_integrity_service.backfill_chain(
        db,
        tenant_id=current_user.tenant_id,
        dry_run=payload.dry_run,
    )
    if not payload.dry_run:
        db.commit()
    return response


@router.get("/checkpoints", response_model=list[AuditIntegrityCheckpointResponse])
def list_audit_integrity_checkpoints(
    current_user=Depends(
        require_roles(
            UserRole.OWNER,
            UserRole.ADMIN,
            UserRole.SECURITY_REVIEWER,
        )
    ),
    db: Session = Depends(get_db),
) -> list[AuditIntegrityCheckpointResponse]:
    return audit_integrity_checkpoint_service.list_checkpoints(
        db,
        tenant_id=current_user.tenant_id,
    )


@router.post("/checkpoints", response_model=AuditIntegrityCheckpointRunResponse)
def create_audit_integrity_checkpoint(
    payload: AuditIntegrityCheckpointCreateRequest,
    request: Request,
    current_user=Depends(
        require_roles(
            UserRole.OWNER,
            UserRole.ADMIN,
            UserRole.SECURITY_REVIEWER,
        )
    ),
    db: Session = Depends(get_db),
) -> AuditIntegrityCheckpointRunResponse:
    del payload
    get_rate_limiter().enforce(
        scope="audit_integrity",
        key_parts=[
            request.client.host if request.client else None,
            current_user.tenant_id,
            current_user.id,
            "checkpoint_create",
        ],
        settings=get_rate_limit_settings("audit_integrity"),
        db=db,
        tenant_id=current_user.tenant_id,
        actor_type=AuditActorType.USER,
        actor_id=current_user.id,
        ip_address=request.client.host if request.client else None,
        audit_on_exhaustion=True,
        resource_type="tenant",
        resource_id=current_user.tenant_id,
        metadata={"endpoint": "audit_integrity.checkpoints.create"},
    )
    job = audit_integrity_checkpoint_service.enqueue_checkpoint_job(
        db,
        tenant_id=current_user.tenant_id,
        requested_by=current_user,
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    try:
        audit_integrity_checkpoint_service.job_service.dispatch_after_commit(
            db,
            job_id=job.id,
            raise_on_error=True,
        )
    except AppError as exc:
        if exc.code == "audit_integrity_checkpoint_chain_broken":
            raise AppError(
                "Audit chain verification failed for the requested checkpoint range.",
                status_code=409,
                code=exc.code,
            ) from exc
        raise
    refreshed_job = audit_integrity_checkpoint_service.job_service.get_job(
        db,
        job_id=job.id,
        tenant_id=current_user.tenant_id,
    ) or job
    return AuditIntegrityCheckpointRunResponse(
        dispatch_mode=(
            "inline" if audit_integrity_checkpoint_service.job_service.is_inline_dispatch() else "worker"
        ),
        job=serialize_job(refreshed_job),
        result=audit_integrity_checkpoint_service.get_job_result(
            db,
            job_id=job.id,
            tenant_id=current_user.tenant_id,
        ),
    )


@router.get("/checkpoints/{checkpoint_id}", response_model=AuditIntegrityCheckpointResponse)
def get_audit_integrity_checkpoint(
    checkpoint_id: str,
    current_user=Depends(
        require_roles(
            UserRole.OWNER,
            UserRole.ADMIN,
            UserRole.SECURITY_REVIEWER,
        )
    ),
    db: Session = Depends(get_db),
) -> AuditIntegrityCheckpointResponse:
    checkpoint = audit_integrity_checkpoint_service.get_checkpoint_or_raise(
        db,
        tenant_id=current_user.tenant_id,
        checkpoint_id=checkpoint_id,
    )
    return audit_integrity_checkpoint_service.serialize_checkpoint(checkpoint)


@router.post("/checkpoints/{checkpoint_id}/verify", response_model=AuditIntegrityCheckpointVerifyResponse)
def verify_audit_integrity_checkpoint(
    checkpoint_id: str,
    request: Request,
    current_user=Depends(
        require_roles(
            UserRole.OWNER,
            UserRole.ADMIN,
            UserRole.SECURITY_REVIEWER,
        )
    ),
    db: Session = Depends(get_db),
) -> AuditIntegrityCheckpointVerifyResponse:
    get_rate_limiter().enforce(
        scope="audit_integrity",
        key_parts=[
            request.client.host if request.client else None,
            current_user.tenant_id,
            current_user.id,
            checkpoint_id,
            "checkpoint_verify",
        ],
        settings=get_rate_limit_settings("audit_integrity"),
        db=db,
        tenant_id=current_user.tenant_id,
        actor_type=AuditActorType.USER,
        actor_id=current_user.id,
        ip_address=request.client.host if request.client else None,
        audit_on_exhaustion=True,
        resource_type="audit_integrity_checkpoint",
        resource_id=checkpoint_id,
        metadata={"endpoint": "audit_integrity.checkpoints.verify"},
    )
    return audit_integrity_checkpoint_service.verify_checkpoint(
        db,
        tenant_id=current_user.tenant_id,
        checkpoint_id=checkpoint_id,
    )
