from __future__ import annotations

import os
import socket
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.enums import WorkerStatus
from app.models import Worker
from app.models.base import utcnow
from app.services.payload_service import PayloadService


payload_service = PayloadService()


@dataclass(frozen=True, slots=True)
class WorkerIdentity:
    worker_id: str
    hostname: str
    process_id: int | None


class WorkerService:
    def build_identity(self) -> WorkerIdentity:
        settings = get_settings()
        hostname = socket.gethostname()
        process_id = os.getpid()
        configured_id = str(settings.worker_id or "").strip()
        worker_id = configured_id or f"{hostname}:{process_id}:{uuid.uuid4().hex[:8]}"
        return WorkerIdentity(
            worker_id=worker_id,
            hostname=hostname,
            process_id=process_id,
        )

    def heartbeat(
        self,
        db: Session,
        *,
        identity: WorkerIdentity,
        metadata: dict | None = None,
    ) -> Worker:
        worker = db.scalar(select(Worker).where(Worker.worker_id == identity.worker_id))
        now = utcnow()
        safe_metadata = payload_service.sanitize_payload(metadata or {})
        if worker is None:
            worker = Worker(
                worker_id=identity.worker_id,
                hostname=identity.hostname,
                process_id=identity.process_id,
                status=WorkerStatus.RUNNING,
                last_heartbeat_at=now,
                started_at=now,
                stopped_at=None,
                metadata_json=safe_metadata,
            )
            db.add(worker)
            db.commit()
            db.refresh(worker)
            return worker

        worker.hostname = identity.hostname
        worker.process_id = identity.process_id
        worker.status = WorkerStatus.RUNNING
        worker.last_heartbeat_at = now
        worker.stopped_at = None
        worker.metadata_json = safe_metadata
        worker.updated_at = now
        db.commit()
        db.refresh(worker)
        return worker

    def mark_stopped(self, db: Session, *, identity: WorkerIdentity) -> Worker | None:
        worker = db.scalar(select(Worker).where(Worker.worker_id == identity.worker_id))
        if worker is None:
            return None
        now = utcnow()
        worker.status = WorkerStatus.STOPPED
        worker.last_heartbeat_at = now
        worker.stopped_at = now
        worker.updated_at = now
        db.commit()
        db.refresh(worker)
        return worker

    def list_workers(
        self,
        db: Session,
        *,
        limit: int = 100,
        include_stopped: bool = True,
    ) -> list[Worker]:
        query = select(Worker)
        if not include_stopped:
            query = query.where(Worker.status != WorkerStatus.STOPPED)
        query = query.order_by(Worker.last_heartbeat_at.desc(), Worker.started_at.desc()).limit(limit)
        return list(db.scalars(query))

    def summarize_workers(self, db: Session) -> dict[str, object]:
        workers = self.list_workers(db, limit=500, include_stopped=True)
        counts = {
            WorkerStatus.RUNNING.value: 0,
            WorkerStatus.STALE.value: 0,
            WorkerStatus.STOPPED.value: 0,
        }
        latest_heartbeat_at: datetime | None = None
        for worker in workers:
            status = self.effective_status(worker)
            counts[status.value] = counts.get(status.value, 0) + 1
            heartbeat = worker.last_heartbeat_at
            if latest_heartbeat_at is None or self._normalize_datetime(heartbeat) > self._normalize_datetime(
                latest_heartbeat_at
            ):
                latest_heartbeat_at = heartbeat
        return {
            "total_workers": len(workers),
            "running_workers": counts[WorkerStatus.RUNNING.value],
            "stale_workers": counts[WorkerStatus.STALE.value],
            "stopped_workers": counts[WorkerStatus.STOPPED.value],
            "latest_heartbeat_at": latest_heartbeat_at,
        }

    def effective_status(self, worker: Worker) -> WorkerStatus:
        if worker.status == WorkerStatus.STOPPED:
            return WorkerStatus.STOPPED
        stale_after = timedelta(seconds=get_settings().worker_stale_after_seconds)
        if self._normalize_datetime(worker.last_heartbeat_at) <= utcnow() - stale_after:
            return WorkerStatus.STALE
        return WorkerStatus.RUNNING

    def runtime_metadata(self) -> dict[str, object]:
        settings = get_settings()
        return {
            "environment": settings.environment,
            "dispatch_mode": settings.job_dispatch_mode,
            "job_broker": settings.job_broker,
            "batch_size": settings.job_worker_batch_size,
            "lease_seconds": settings.job_lease_seconds,
            "heartbeat_interval_seconds": settings.worker_heartbeat_interval_seconds,
        }

    def _normalize_datetime(self, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
