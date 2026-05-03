from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy import Select, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.core.enums import JobStatus, JobType
from app.core.errors import AppError
from app.core.logging import get_logger
from app.core.metrics import get_metrics_registry
from app.core.redaction import redact_sensitive_string
from app.models import Job
from app.models.base import utcnow

logger = get_logger(__name__)


@dataclass(slots=True)
class JobProcessingError(Exception):
    detail: str
    code: str = "job_processing_failed"
    retryable: bool = False
    persist_state: bool = False

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.detail

    def to_app_error(self) -> AppError:
        status_code = 503 if self.retryable else 500
        return AppError(self.detail, status_code=status_code, code=self.code)


class RedisJobBroker:
    def __init__(self, *, redis_url: str, queue_name: str) -> None:
        self.queue_name = queue_name
        self.client = Redis.from_url(redis_url, decode_responses=True)

    def publish(self, job_id: str) -> None:
        self.client.rpush(self.queue_name, job_id)

    def pop(self, *, timeout_seconds: float) -> str | None:
        timeout = max(1, int(timeout_seconds))
        message = self.client.blpop(self.queue_name, timeout=timeout)
        if not message:
            return None
        _, job_id = message
        return str(job_id)


class JobService:
    def __init__(self) -> None:
        self._broker = None
        self.metrics = get_metrics_registry()

    def enqueue(
        self,
        db: Session,
        *,
        tenant_id: str,
        job_type: JobType,
        idempotency_key: str,
        payload: dict,
        max_attempts: int = 1,
    ) -> Job:
        existing = db.scalar(
            select(Job).where(
                Job.tenant_id == tenant_id,
                Job.idempotency_key == idempotency_key,
            )
        )
        if existing:
            return existing

        job = Job(
            tenant_id=tenant_id,
            job_type=job_type,
            status=JobStatus.QUEUED,
            idempotency_key=idempotency_key,
            payload=payload,
            attempts=0,
            max_attempts=max(1, max_attempts),
            next_run_at=utcnow(),
            last_error=None,
            completed_at=None,
        )
        db.add(job)
        db.flush()
        self.metrics.increment(
            "agentgate_jobs_transitions_total",
            job_type=job.job_type.value,
            status=JobStatus.QUEUED.value,
        )
        return job

    def dispatch_after_commit(
        self,
        db: Session,
        *,
        job_id: str,
        raise_on_error: bool = False,
    ) -> Job | None:
        if self.is_inline_dispatch():
            return self.process_job(db, job_id=job_id, raise_on_error=raise_on_error)
        self.publish(job_id)
        return self.get_job(db, job_id=job_id)

    def is_inline_dispatch(self) -> bool:
        return get_settings().job_dispatch_mode == "inline"

    def publish(self, job_id: str) -> None:
        broker = self._get_broker()
        if not broker:
            return
        try:
            broker.publish(job_id)
        except RedisError:
            logger.warning(
                "job_publish_failed",
                extra={"event_type": "job_publish_failed"},
                exc_info=True,
            )

    def pop_published_job_id(self, *, timeout_seconds: float | None = None) -> str | None:
        broker = self._get_broker()
        if not broker:
            return None
        try:
            return broker.pop(
                timeout_seconds=timeout_seconds or get_settings().job_poll_interval_seconds,
            )
        except RedisError:
            logger.warning(
                "job_broker_unavailable",
                extra={"event_type": "job_broker_unavailable"},
                exc_info=True,
            )
            return None

    def get_job(self, db: Session, *, job_id: str, tenant_id: str | None = None) -> Job | None:
        query = select(Job).where(Job.id == job_id)
        if tenant_id:
            query = query.where(Job.tenant_id == tenant_id)
        return db.scalar(query)

    def list_jobs(
        self,
        db: Session,
        *,
        tenant_id: str,
        status: JobStatus | None = None,
        job_type: JobType | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Job]:
        query = select(Job).where(Job.tenant_id == tenant_id)
        if status:
            query = query.where(Job.status == status)
        if job_type:
            query = query.where(Job.job_type == job_type)
        return list(db.scalars(query.order_by(Job.created_at.desc()).offset(offset).limit(limit)))

    def process_job(
        self,
        db: Session,
        *,
        job_id: str,
        raise_on_error: bool = False,
    ) -> Job | None:
        claimed = self._claim_job_by_id(db, job_id=job_id)
        if not claimed:
            return self.get_job(db, job_id=job_id)
        return self._run_claimed_job(db, job_id=job_id, raise_on_error=raise_on_error)

    def process_due_jobs(
        self,
        *,
        session_factory: sessionmaker,
        limit: int | None = None,
    ) -> int:
        max_jobs = limit or get_settings().job_worker_batch_size
        processed = 0
        for _ in range(max_jobs):
            with session_factory() as claim_session:
                job_id = self._claim_next_due_job(claim_session)
            if not job_id:
                break
            with session_factory() as run_session:
                self._run_claimed_job(run_session, job_id=job_id, raise_on_error=False)
            processed += 1
        return processed

    def _claim_next_due_job(self, db: Session) -> str | None:
        now = utcnow()
        query: Select[tuple[Job]] = (
            select(Job)
            .where(
                Job.status == JobStatus.QUEUED,
                Job.next_run_at <= now,
            )
            .order_by(Job.next_run_at.asc(), Job.created_at.asc())
            .limit(1)
        )
        if db.bind and db.bind.dialect.name == "postgresql":
            query = query.with_for_update(skip_locked=True)
        job = db.scalar(query)
        if not job:
            return None
        if self._normalize_datetime(job.next_run_at) > now:
            return None
        self._mark_running(db, job)
        return job.id

    def _claim_job_by_id(self, db: Session, *, job_id: str) -> bool:
        now = utcnow()
        query: Select[tuple[Job]] = select(Job).where(Job.id == job_id)
        if db.bind and db.bind.dialect.name == "postgresql":
            query = query.with_for_update(skip_locked=True)
        job = db.scalar(query)
        if not job:
            return False
        if job.status != JobStatus.QUEUED:
            return False
        if self._normalize_datetime(job.next_run_at) > now:
            return False
        self._mark_running(db, job)
        return True

    def _mark_running(self, db: Session, job: Job) -> None:
        job.status = JobStatus.RUNNING
        job.attempts += 1
        job.last_error = None
        job.updated_at = utcnow()
        db.commit()
        self.metrics.increment(
            "agentgate_jobs_transitions_total",
            job_type=job.job_type.value,
            status=JobStatus.RUNNING.value,
        )

    def _run_claimed_job(
        self,
        db: Session,
        *,
        job_id: str,
        raise_on_error: bool,
    ) -> Job | None:
        job = self.get_job(db, job_id=job_id)
        if not job or job.status != JobStatus.RUNNING:
            return job

        try:
            from app.jobs.dispatcher import dispatch_job

            dispatch_job(db, job)
            job.status = JobStatus.SUCCEEDED
            job.last_error = None
            job.completed_at = utcnow()
            job.updated_at = utcnow()
            db.commit()
            self.metrics.increment(
                "agentgate_jobs_transitions_total",
                job_type=job.job_type.value,
                status=JobStatus.SUCCEEDED.value,
            )
            return job
        except JobProcessingError as exc:
            if not exc.persist_state:
                db.rollback()
            return self._handle_job_error(db, job_id=job_id, exc=exc, raise_on_error=raise_on_error)
        except AppError as exc:
            db.rollback()
            wrapped = JobProcessingError(detail=exc.detail, code=exc.code, retryable=False)
            return self._handle_job_error(db, job_id=job_id, exc=wrapped, raise_on_error=raise_on_error)
        except Exception as exc:  # pragma: no cover - fail-closed safeguard
            db.rollback()
            wrapped = JobProcessingError(
                detail="Job handler failed unexpectedly.",
                code="job_handler_failed",
                retryable=False,
            )
            logger.warning(
                "job_handler_failed",
                extra={"event_type": "job_handler_failed"},
                exc_info=True,
            )
            return self._handle_job_error(db, job_id=job_id, exc=wrapped, raise_on_error=raise_on_error)

    def _handle_job_error(
        self,
        db: Session,
        *,
        job_id: str,
        exc: JobProcessingError,
        raise_on_error: bool,
    ) -> Job | None:
        from app.jobs.dispatcher import dispatch_job_retry_exhausted

        job = self.get_job(db, job_id=job_id)
        if not job:
            if raise_on_error:
                raise exc.to_app_error()
            return None

        detail = redact_sensitive_string(exc.detail)
        retryable = exc.retryable and job.attempts < job.max_attempts
        job.last_error = detail
        job.updated_at = utcnow()
        if retryable:
            job.status = JobStatus.QUEUED
            job.next_run_at = utcnow() + timedelta(seconds=self._retry_delay_seconds(job.job_type))
            job.completed_at = None
        else:
            exhausted = exc.retryable and job.max_attempts > 1 and job.attempts >= job.max_attempts
            job.status = JobStatus.RETRY_EXHAUSTED if exhausted else JobStatus.FAILED
            job.completed_at = utcnow()
            if exhausted:
                dispatch_job_retry_exhausted(db, job)
        db.commit()
        self.metrics.increment(
            "agentgate_jobs_transitions_total",
            job_type=job.job_type.value,
            status=job.status.value,
        )
        logger.warning(
            "job_failed",
            extra={
                "event_type": "job_failed",
                "tenant_id": job.tenant_id,
            },
        )
        if raise_on_error:
            raise exc.to_app_error()
        return job

    def _retry_delay_seconds(self, job_type: JobType) -> float:
        settings = get_settings()
        if job_type == JobType.APPROVAL_NOTIFICATION_SLACK:
            return max(0.0, settings.job_slack_retry_backoff_seconds)
        if job_type == JobType.AUDIT_EXPORT_PLACEHOLDER:
            return max(0.0, settings.job_audit_export_retry_backoff_seconds)
        if job_type == JobType.RETENTION_PURGE_PLACEHOLDER:
            return max(0.0, settings.job_retention_retry_backoff_seconds)
        return 0.0

    def _get_broker(self) -> RedisJobBroker | None:
        settings = get_settings()
        if settings.job_broker != "redis":
            return None
        if not settings.redis_url:
            return None
        if self._broker is None:
            self._broker = RedisJobBroker(
                redis_url=settings.redis_url,
                queue_name=settings.job_redis_queue_name,
            )
        return self._broker

    def _normalize_datetime(self, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
