from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.metrics import get_metrics_registry
from app.core.redaction import redact_sensitive_string
from app.models import Job

router = APIRouter()


@router.get("/metrics")
def metrics(db: Session = Depends(get_db)) -> Response:
    registry = get_metrics_registry()
    _refresh_job_gauges(registry, db)
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
