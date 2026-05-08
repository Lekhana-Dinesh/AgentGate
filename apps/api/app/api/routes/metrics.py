from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.enums import ScheduledTaskType
from app.core.metrics import get_metrics_registry
from app.core.redaction import redact_sensitive_string
from app.models import Job, ScheduledTask
from app.services.worker_service import WorkerService
from app.services.scheduled_task_service import (
    SCHEDULED_TASK_STATUS_DUPLICATE,
    SCHEDULED_TASK_STATUS_ENQUEUED,
    SCHEDULED_TASK_STATUS_FAILED,
    SCHEDULED_TASK_STATUS_IDLE,
)
from app.models.base import utcnow

router = APIRouter()
worker_service = WorkerService()


@router.get("/metrics")
def metrics(db: Session = Depends(get_db)) -> Response:
    registry = get_metrics_registry()
    _refresh_job_gauges(registry, db)
    _refresh_scheduler_gauges(registry, db)
    body = redact_sensitive_string(registry.render_prometheus())
    return Response(
        content=body,
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


def _refresh_job_gauges(registry, db: Session) -> None:
    registry.set_gauge("agentgate_jobs_current", 0, status="queued")
    registry.set_gauge("agentgate_jobs_current", 0, status="running")
    registry.set_gauge("agentgate_jobs_current", 0, status="succeeded")
    registry.set_gauge("agentgate_jobs_current", 0, status="failed")
    registry.set_gauge("agentgate_jobs_current", 0, status="retry_exhausted")
    registry.set_gauge("agentgate_jobs_current", 0, status="cancelled")
    registry.set_gauge("agentgate_jobs_dead_letter_current", 0, status="failed")
    registry.set_gauge("agentgate_jobs_dead_letter_current", 0, status="retry_exhausted")
    registry.set_gauge("agentgate_workers_current", 0, status="running")
    registry.set_gauge("agentgate_workers_current", 0, status="stale")
    registry.set_gauge("agentgate_workers_current", 0, status="stopped")

    try:
        rows = list(
            db.execute(
                select(Job.status, func.count(Job.id))
                .group_by(Job.status)
            )
        )
    except Exception:
        return

    for status, count in rows:
        registry.set_gauge(
            "agentgate_jobs_current",
            float(count),
            status=str(status.value if hasattr(status, "value") else status),
        )

    try:
        dead_letter_rows = list(
            db.execute(
                select(Job.status, func.count(Job.id))
                .where(Job.dead_letter_reason.is_not(None))
                .group_by(Job.status)
            )
        )
    except Exception:
        dead_letter_rows = []

    for status, count in dead_letter_rows:
        registry.set_gauge(
            "agentgate_jobs_dead_letter_current",
            float(count),
            status=str(status.value if hasattr(status, "value") else status),
        )

    try:
        summary = worker_service.summarize_workers(db)
    except Exception:
        return

    registry.set_gauge("agentgate_workers_current", float(summary["running_workers"]), status="running")
    registry.set_gauge("agentgate_workers_current", float(summary["stale_workers"]), status="stale")
    registry.set_gauge("agentgate_workers_current", float(summary["stopped_workers"]), status="stopped")


def _refresh_scheduler_gauges(registry, db: Session) -> None:
    for task_type in ScheduledTaskType:
        registry.set_gauge("agentgate_scheduled_tasks_due_current", 0, task_type=task_type.value)
    for status in (
        SCHEDULED_TASK_STATUS_IDLE,
        SCHEDULED_TASK_STATUS_ENQUEUED,
        SCHEDULED_TASK_STATUS_DUPLICATE,
        SCHEDULED_TASK_STATUS_FAILED,
    ):
        registry.set_gauge("agentgate_scheduled_tasks_last_status_current", 0, last_status=status)

    try:
        due_rows = list(
            db.execute(
                select(ScheduledTask.task_type, func.count(ScheduledTask.id))
                .where(
                    ScheduledTask.enabled.is_(True),
                    ScheduledTask.next_run_at <= utcnow(),
                )
                .group_by(ScheduledTask.task_type)
            )
        )
    except Exception:
        return

    for task_type, count in due_rows:
        registry.set_gauge(
            "agentgate_scheduled_tasks_due_current",
            float(count),
            task_type=str(task_type.value if hasattr(task_type, "value") else task_type),
        )

    try:
        last_status_rows = list(
            db.execute(
                select(ScheduledTask.last_status, func.count(ScheduledTask.id))
                .where(ScheduledTask.last_status.is_not(None))
                .group_by(ScheduledTask.last_status)
            )
        )
    except Exception:
        return

    for last_status, count in last_status_rows:
        registry.set_gauge(
            "agentgate_scheduled_tasks_last_status_current",
            float(count),
            last_status=str(last_status),
        )
