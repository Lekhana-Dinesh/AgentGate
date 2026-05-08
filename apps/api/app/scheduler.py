from __future__ import annotations

import os
import socket
import time
import uuid

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.core.metrics import get_metrics_registry
from app.db.session import SessionLocal
from app.services.scheduled_task_service import ScheduledTaskService

configure_logging()
logger = get_logger(__name__)


def _build_scheduler_id() -> str:
    hostname = socket.gethostname()
    process_id = os.getpid()
    return f"{hostname}:{process_id}:{uuid.uuid4().hex[:8]}"


def main() -> None:
    settings = get_settings()
    scheduler_id = _build_scheduler_id()
    scheduler_service = ScheduledTaskService()
    logger.info(
        "agentgate_scheduler_started",
        extra={
            "event_type": "agentgate_scheduler_started",
            "environment": settings.environment,
            "scheduler_id": scheduler_id,
        },
    )
    try:
        while True:
            try:
                processed = scheduler_service.process_due_tasks(
                    session_factory=SessionLocal,
                    limit=settings.scheduler_batch_size,
                    scheduler_id=scheduler_id,
                )
            except KeyboardInterrupt:
                raise
            except Exception:
                get_metrics_registry().increment(
                    "agentgate_scheduler_errors_total",
                    task_type="scheduler",
                    trigger="loop",
                    error_code="unexpected_error",
                )
                logger.warning(
                    "agentgate_scheduler_iteration_failed",
                    extra={
                        "event_type": "agentgate_scheduler_iteration_failed",
                        "scheduler_id": scheduler_id,
                    },
                    exc_info=True,
                )
                processed = 0
            if processed == 0:
                time.sleep(settings.scheduler_poll_interval_seconds)
    except KeyboardInterrupt:
        logger.info(
            "agentgate_scheduler_stopped",
            extra={
                "event_type": "agentgate_scheduler_stopped",
                "environment": settings.environment,
                "scheduler_id": scheduler_id,
            },
        )


if __name__ == "__main__":
    main()
