from __future__ import annotations

import time

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.db.session import SessionLocal
from app.services.job_service import JobService
from app.services.worker_service import WorkerService

configure_logging()
logger = get_logger(__name__)


def main() -> None:
    settings = get_settings()
    job_service = JobService()
    worker_service = WorkerService()
    identity = worker_service.build_identity()
    next_heartbeat_at = 0.0
    with SessionLocal() as db:
        worker_service.heartbeat(
            db,
            identity=identity,
            metadata=worker_service.runtime_metadata(),
        )
    logger.info(
        "agentgate_worker_started",
        extra={
            "event_type": "agentgate_worker_started",
            "environment": settings.environment,
            "worker_id": identity.worker_id,
        },
    )
    try:
        while True:
            now = time.monotonic()
            if now >= next_heartbeat_at:
                with SessionLocal() as db:
                    worker_service.heartbeat(
                        db,
                        identity=identity,
                        metadata=worker_service.runtime_metadata(),
                    )
                next_heartbeat_at = now + settings.worker_heartbeat_interval_seconds

            processed = 0
            processed += job_service.recover_stale_jobs(
                session_factory=SessionLocal,
                limit=settings.job_stale_recovery_batch_size,
            )
            published_job_id = None
            if settings.job_broker == "redis":
                published_job_id = job_service.pop_published_job_id(
                    timeout_seconds=settings.job_poll_interval_seconds,
                )
            if published_job_id:
                with SessionLocal() as db:
                    job_service.process_job(
                        db,
                        job_id=published_job_id,
                        raise_on_error=False,
                        worker_id=identity.worker_id,
                    )
                processed += 1

            processed += job_service.process_due_jobs(
                session_factory=SessionLocal,
                limit=settings.job_worker_batch_size,
                worker_id=identity.worker_id,
            )
            if processed == 0 and settings.job_broker != "redis":
                time.sleep(settings.job_poll_interval_seconds)
    except KeyboardInterrupt:
        logger.info(
            "agentgate_worker_stopped",
            extra={
                "event_type": "agentgate_worker_stopped",
                "environment": settings.environment,
                "worker_id": identity.worker_id,
            },
        )
    finally:
        with SessionLocal() as db:
            worker_service.mark_stopped(db, identity=identity)


if __name__ == "__main__":
    main()
