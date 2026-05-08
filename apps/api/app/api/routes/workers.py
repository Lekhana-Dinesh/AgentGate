from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.core.enums import UserRole
from app.db.session import get_db
from app.schemas.worker import WorkerResponse, WorkerStatusResponse
from app.services.worker_service import WorkerService

router = APIRouter()
worker_service = WorkerService()


@router.get("", response_model=list[WorkerResponse])
def list_workers(
    include_stopped: bool = Query(default=True),
    limit: int = Query(default=100, ge=1, le=500),
    current_user=Depends(
        require_roles(
            UserRole.OWNER,
            UserRole.ADMIN,
            UserRole.SECURITY_REVIEWER,
        )
    ),
    db: Session = Depends(get_db),
) -> list[WorkerResponse]:
    workers = worker_service.list_workers(
        db,
        limit=limit,
        include_stopped=include_stopped,
    )
    return [
        WorkerResponse(
            id=worker.id,
            worker_id=worker.worker_id,
            hostname=worker.hostname,
            process_id=worker.process_id,
            status=worker_service.effective_status(worker).value,
            last_heartbeat_at=worker.last_heartbeat_at,
            started_at=worker.started_at,
            stopped_at=worker.stopped_at,
            metadata=worker.metadata_json or {},
            created_at=worker.created_at,
            updated_at=worker.updated_at,
        )
        for worker in workers
    ]


@router.get("/status", response_model=WorkerStatusResponse)
def get_worker_status(
    current_user=Depends(
        require_roles(
            UserRole.OWNER,
            UserRole.ADMIN,
            UserRole.SECURITY_REVIEWER,
        )
    ),
    db: Session = Depends(get_db),
) -> WorkerStatusResponse:
    return WorkerStatusResponse(**worker_service.summarize_workers(db))
