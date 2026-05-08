from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.core.enums import AuditActorType, UserRole
from app.db.session import get_db
from app.schemas.job import serialize_job
from app.schemas.scheduled_task import (
    ScheduledTaskCreate,
    ScheduledTaskResponse,
    ScheduledTaskRunNowResponse,
    ScheduledTaskUpdate,
)
from app.services.scheduled_task_service import ScheduledTaskService

router = APIRouter()
scheduled_task_service = ScheduledTaskService()


@router.get("", response_model=list[ScheduledTaskResponse])
def list_scheduled_tasks(
    current_user=Depends(
        require_roles(
            UserRole.OWNER,
            UserRole.ADMIN,
            UserRole.SECURITY_REVIEWER,
        )
    ),
    db: Session = Depends(get_db),
) -> list[ScheduledTaskResponse]:
    return scheduled_task_service.list_tasks(db, tenant_id=current_user.tenant_id)


@router.get("/{task_id}", response_model=ScheduledTaskResponse)
def get_scheduled_task(
    task_id: str,
    current_user=Depends(
        require_roles(
            UserRole.OWNER,
            UserRole.ADMIN,
            UserRole.SECURITY_REVIEWER,
        )
    ),
    db: Session = Depends(get_db),
) -> ScheduledTaskResponse:
    task = scheduled_task_service.get_task_or_raise(
        db,
        tenant_id=current_user.tenant_id,
        task_id=task_id,
    )
    return scheduled_task_service.serialize_task(task)


@router.post("", response_model=ScheduledTaskResponse, status_code=status.HTTP_201_CREATED)
def create_scheduled_task(
    payload: ScheduledTaskCreate,
    request: Request,
    current_user=Depends(
        require_roles(
            UserRole.OWNER,
            UserRole.ADMIN,
        )
    ),
    db: Session = Depends(get_db),
) -> ScheduledTaskResponse:
    task = scheduled_task_service.create_task(
        db,
        tenant_id=current_user.tenant_id,
        payload=payload,
        actor_type=AuditActorType.USER,
        actor_id=current_user.id,
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    return scheduled_task_service.serialize_task(task)


@router.patch("/{task_id}", response_model=ScheduledTaskResponse)
def update_scheduled_task(
    task_id: str,
    payload: ScheduledTaskUpdate,
    request: Request,
    current_user=Depends(
        require_roles(
            UserRole.OWNER,
            UserRole.ADMIN,
        )
    ),
    db: Session = Depends(get_db),
) -> ScheduledTaskResponse:
    task = scheduled_task_service.update_task(
        db,
        tenant_id=current_user.tenant_id,
        task_id=task_id,
        payload=payload,
        actor_type=AuditActorType.USER,
        actor_id=current_user.id,
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    return scheduled_task_service.serialize_task(task)


@router.post("/{task_id}/run-now", response_model=ScheduledTaskRunNowResponse)
def run_scheduled_task_now(
    task_id: str,
    request: Request,
    current_user=Depends(
        require_roles(
            UserRole.OWNER,
            UserRole.ADMIN,
        )
    ),
    db: Session = Depends(get_db),
) -> ScheduledTaskRunNowResponse:
    result = scheduled_task_service.run_now(
        db,
        tenant_id=current_user.tenant_id,
        task_id=task_id,
        actor_type=AuditActorType.USER,
        actor_id=current_user.id,
        ip_address=request.client.host if request.client else None,
    )
    if result.created:
        scheduled_task_service.job_service.dispatch_after_commit(
            db,
            job_id=result.job.id,
            raise_on_error=True,
        )
    task = scheduled_task_service.get_task_or_raise(
        db,
        tenant_id=current_user.tenant_id,
        task_id=task_id,
    )
    job = scheduled_task_service.job_service.get_job(
        db,
        job_id=result.job.id,
        tenant_id=current_user.tenant_id,
    ) or result.job
    return ScheduledTaskRunNowResponse(
        dispatch_mode="inline" if scheduled_task_service.job_service.is_inline_dispatch() else "worker",
        job=serialize_job(job),
        scheduled_task=scheduled_task_service.serialize_task(task),
    )
