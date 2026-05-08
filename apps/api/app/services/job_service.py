from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy import Select, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.core.enums import AuditActorType, JobStatus, JobType
from app.core.errors import AppError
from app.core.logging import get_logger
from app.core.metrics import get_metrics_registry
from app.core.redaction import redact_sensitive_string
from app.models import Job
from app.models.base import utcnow

logger = get_logger(__name__)

JOB_STALE_RECOVERED_EVENT = "job.stale_recovered"
JOB_DEAD_LETTERED_EVENT = "job.dead_lettered"
JOB_MANUAL_RETRY_EVENT = "job.retry_requested"


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


@dataclass(frozen=True, slots=True)
class JobReliabilityPolicy:
    auto_retry: bool
    manual_retry: bool
    retry_backoff_seconds: float


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
            locked_by=None,
            locked_at=None,
            lease_expires_at=None,
            dead_letter_reason=None,
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
        dead_lettered: bool | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Job]:
        query = select(Job).where(Job.tenant_id == tenant_id)
        if status:
            query = query.where(Job.status == status)
        if job_type:
            query = query.where(Job.job_type == job_type)
        if dead_lettered is True:
            query = query.where(Job.dead_letter_reason.is_not(None))
        elif dead_lettered is False:
            query = query.where(Job.dead_letter_reason.is_(None))
        return list(db.scalars(query.order_by(Job.created_at.desc()).offset(offset).limit(limit)))

    def process_job(
        self,
        db: Session,
        *,
        job_id: str,
        raise_on_error: bool = False,
        worker_id: str | None = None,
    ) -> Job | None:
        claimed = self._claim_job_by_id(db, job_id=job_id, worker_id=worker_id)
        if not claimed:
            return self.get_job(db, job_id=job_id)
        return self._run_claimed_job(db, job_id=job_id, raise_on_error=raise_on_error)

    def process_due_jobs(
        self,
        *,
        session_factory: sessionmaker,
        limit: int | None = None,
        worker_id: str | None = None,
    ) -> int:
        max_jobs = limit or get_settings().job_worker_batch_size
        processed = 0
        for _ in range(max_jobs):
            with session_factory() as claim_session:
                job_id = self._claim_next_due_job(claim_session, worker_id=worker_id)
            if not job_id:
                break
            with session_factory() as run_session:
                self._run_claimed_job(run_session, job_id=job_id, raise_on_error=False)
            processed += 1
        return processed

    def recover_stale_jobs(
        self,
        *,
        session_factory: sessionmaker,
        limit: int | None = None,
    ) -> int:
        max_jobs = limit or get_settings().job_stale_recovery_batch_size
        recovered = 0
        for _ in range(max_jobs):
            with session_factory() as db:
                if not self._recover_one_stale_job(db):
                    break
                recovered += 1
        return recovered

    def retry_job(
        self,
        db: Session,
        *,
        job_id: str,
        tenant_id: str,
        actor_id: str,
        ip_address: str | None,
    ) -> Job:
        job = self.get_job(db, job_id=job_id, tenant_id=tenant_id)
        if not job:
            raise AppError("Job not found.", status_code=404, code="job_not_found")
        if job.status not in {JobStatus.FAILED, JobStatus.RETRY_EXHAUSTED}:
            raise AppError(
                "Only failed or retry-exhausted jobs can be retried.",
                status_code=409,
                code="job_retry_invalid_state",
            )
        if not self.can_retry_manually(job):
            raise AppError(
                "Manual retry is not allowed for this job type because it could duplicate unsafe side effects.",
                status_code=409,
                code="job_retry_not_allowed",
            )

        previous_status = job.status.value
        previous_reason = job.dead_letter_reason
        now = utcnow()
        job.status = JobStatus.QUEUED
        job.next_run_at = now
        job.completed_at = None
        job.last_error = None
        job.dead_letter_reason = None
        self._clear_lease(job)
        job.updated_at = now
        self._record_job_audit(
            db,
            tenant_id=tenant_id,
            event_type=JOB_MANUAL_RETRY_EVENT,
            resource_id=job.id,
            actor_type=AuditActorType.USER,
            actor_id=actor_id,
            ip_address=ip_address,
            metadata={
                "job_type": job.job_type.value,
                "previous_status": previous_status,
                "previous_dead_letter_reason": previous_reason,
            },
        )
        db.commit()
        self.metrics.increment(
            "agentgate_jobs_transitions_total",
            job_type=job.job_type.value,
            status=JobStatus.QUEUED.value,
        )
        self.metrics.increment(
            "agentgate_jobs_retries_total",
            job_type=job.job_type.value,
            trigger="manual",
        )
        return job

    def can_retry_manually(self, job: Job) -> bool:
        return self._policy_for_job_type(job.job_type).manual_retry

    def _claim_next_due_job(self, db: Session, *, worker_id: str | None) -> str | None:
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
        if self._is_postgresql(db):
            query = query.with_for_update(skip_locked=True)
        job = db.scalar(query)
        if not job:
            return None
        if self._normalize_datetime(job.next_run_at) > now:
            return None
        self._mark_running(db, job, worker_id=worker_id)
        return job.id

    def _claim_job_by_id(self, db: Session, *, job_id: str, worker_id: str | None) -> bool:
        now = utcnow()
        query: Select[tuple[Job]] = select(Job).where(Job.id == job_id)
        if self._is_postgresql(db):
            query = query.with_for_update(skip_locked=True)
        job = db.scalar(query)
        if not job:
            return False
        if job.status != JobStatus.QUEUED:
            return False
        if self._normalize_datetime(job.next_run_at) > now:
            return False
        self._mark_running(db, job, worker_id=worker_id)
        return True

    def _mark_running(self, db: Session, job: Job, *, worker_id: str | None) -> None:
        now = utcnow()
        job.status = JobStatus.RUNNING
        job.attempts += 1
        job.last_error = None
        job.dead_letter_reason = None
        job.locked_by = self._claimant_id(worker_id)
        job.locked_at = now
        job.lease_expires_at = now + timedelta(seconds=get_settings().job_lease_seconds)
        job.updated_at = now
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
            job.dead_letter_reason = None
            job.completed_at = utcnow()
            job.updated_at = utcnow()
            self._clear_lease(job)
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
        except Exception:  # pragma: no cover - fail-closed safeguard
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
        policy = self._policy_for_job_type(job.job_type)
        retryable = exc.retryable and policy.auto_retry and job.attempts < job.max_attempts
        job.last_error = detail
        job.updated_at = utcnow()
        self._clear_lease(job)

        if retryable:
            job.status = JobStatus.QUEUED
            job.next_run_at = utcnow() + timedelta(seconds=policy.retry_backoff_seconds)
            job.completed_at = None
            job.dead_letter_reason = None
            db.commit()
            self.metrics.increment(
                "agentgate_jobs_transitions_total",
                job_type=job.job_type.value,
                status=JobStatus.QUEUED.value,
            )
            self.metrics.increment(
                "agentgate_jobs_retries_total",
                job_type=job.job_type.value,
                trigger="automatic",
            )
        else:
            exhausted = exc.retryable and policy.auto_retry and job.max_attempts > 1 and job.attempts >= job.max_attempts
            job.status = JobStatus.RETRY_EXHAUSTED if exhausted else JobStatus.FAILED
            job.dead_letter_reason = exc.code
            job.completed_at = utcnow()
            if exhausted:
                dispatch_job_retry_exhausted(db, job)
            self._record_job_audit(
                db,
                tenant_id=job.tenant_id,
                event_type=JOB_DEAD_LETTERED_EVENT,
                resource_id=job.id,
                actor_type=AuditActorType.SYSTEM,
                actor_id=None,
                ip_address=None,
                metadata={
                    "job_type": job.job_type.value,
                    "status": job.status.value,
                    "reason": job.dead_letter_reason,
                    "attempts": job.attempts,
                    "max_attempts": job.max_attempts,
                },
            )
            db.commit()
            self.metrics.increment(
                "agentgate_jobs_transitions_total",
                job_type=job.job_type.value,
                status=job.status.value,
            )
            self.metrics.increment(
                "agentgate_jobs_dead_letter_total",
                job_type=job.job_type.value,
                status=job.status.value,
            )

        logger.warning(
            "job_failed",
            extra={
                "event_type": "job_failed",
                "tenant_id": job.tenant_id,
                "job_id": job.id,
                "job_type": job.job_type.value,
                "error_code": exc.code,
            },
        )
        if raise_on_error:
            raise exc.to_app_error()
        return job

    def _recover_one_stale_job(self, db: Session) -> bool:
        from app.jobs.dispatcher import dispatch_job_retry_exhausted

        now = utcnow()
        query: Select[tuple[Job]] = (
            select(Job)
            .where(
                Job.status == JobStatus.RUNNING,
                Job.lease_expires_at.is_not(None),
                Job.lease_expires_at <= now,
            )
            .order_by(Job.lease_expires_at.asc(), Job.created_at.asc())
            .limit(1)
        )
        if self._is_postgresql(db):
            query = query.with_for_update(skip_locked=True)
        job = db.scalar(query)
        if not job:
            return False

        policy = self._policy_for_job_type(job.job_type)
        previous_worker_id = job.locked_by
        self.metrics.increment("agentgate_jobs_lease_expired_total", job_type=job.job_type.value)

        if policy.auto_retry and job.attempts < job.max_attempts:
            job.status = JobStatus.QUEUED
            job.next_run_at = now
            job.last_error = "Job lease expired while running. Requeued for safe retry."
            job.dead_letter_reason = None
            job.completed_at = None
            job.updated_at = now
            self._clear_lease(job)
            self._record_job_audit(
                db,
                tenant_id=job.tenant_id,
                event_type=JOB_STALE_RECOVERED_EVENT,
                resource_id=job.id,
                actor_type=AuditActorType.SYSTEM,
                actor_id=None,
                ip_address=None,
                metadata={
                    "job_type": job.job_type.value,
                    "action": "requeued",
                    "previous_locked_by": previous_worker_id,
                    "attempts": job.attempts,
                    "max_attempts": job.max_attempts,
                },
            )
            db.commit()
            self.metrics.increment(
                "agentgate_jobs_transitions_total",
                job_type=job.job_type.value,
                status=JobStatus.QUEUED.value,
            )
            self.metrics.increment(
                "agentgate_jobs_retries_total",
                job_type=job.job_type.value,
                trigger="stale_recovery",
            )
            self.metrics.increment(
                "agentgate_jobs_stale_recovered_total",
                job_type=job.job_type.value,
                outcome="requeued",
            )
            return True

        exhausted = policy.auto_retry
        job.status = JobStatus.RETRY_EXHAUSTED if exhausted else JobStatus.FAILED
        job.last_error = (
            "Job lease expired while running and was moved to dead-letter review."
            if not exhausted
            else "Job lease expired while running after retry attempts were exhausted."
        )
        job.dead_letter_reason = (
            "lease_expired_attempts_exhausted" if exhausted else "lease_expired_non_retryable"
        )
        job.completed_at = now
        job.updated_at = now
        self._clear_lease(job)
        if exhausted:
            dispatch_job_retry_exhausted(db, job)
        self._record_job_audit(
            db,
            tenant_id=job.tenant_id,
            event_type=JOB_DEAD_LETTERED_EVENT,
            resource_id=job.id,
            actor_type=AuditActorType.SYSTEM,
            actor_id=None,
            ip_address=None,
            metadata={
                "job_type": job.job_type.value,
                "status": job.status.value,
                "reason": job.dead_letter_reason,
                "previous_locked_by": previous_worker_id,
                "attempts": job.attempts,
                "max_attempts": job.max_attempts,
                "manual_review_required": True,
            },
        )
        db.commit()
        self.metrics.increment(
            "agentgate_jobs_transitions_total",
            job_type=job.job_type.value,
            status=job.status.value,
        )
        self.metrics.increment(
            "agentgate_jobs_dead_letter_total",
            job_type=job.job_type.value,
            status=job.status.value,
        )
        self.metrics.increment(
            "agentgate_jobs_stale_recovered_total",
            job_type=job.job_type.value,
            outcome="dead_lettered",
        )
        return True

    def _record_job_audit(
        self,
        db: Session,
        *,
        tenant_id: str,
        event_type: str,
        resource_id: str,
        actor_type: AuditActorType,
        actor_id: str | None,
        ip_address: str | None,
        metadata: dict,
    ) -> None:
        from app.services.audit_service import AuditService

        AuditService().create_event(
            db,
            tenant_id=tenant_id,
            actor_type=actor_type,
            actor_id=actor_id,
            event_type=event_type,
            resource_type="job",
            resource_id=resource_id,
            metadata=metadata,
            ip_address=ip_address,
        )

    def _clear_lease(self, job: Job) -> None:
        job.locked_by = None
        job.locked_at = None
        job.lease_expires_at = None

    def _policy_for_job_type(self, job_type: JobType) -> JobReliabilityPolicy:
        settings = get_settings()
        if job_type == JobType.APPROVAL_NOTIFICATION_SLACK:
            return JobReliabilityPolicy(
                auto_retry=True,
                manual_retry=True,
                retry_backoff_seconds=max(0.0, settings.job_slack_retry_backoff_seconds),
            )
        if job_type == JobType.AUDIT_EXPORT_PLACEHOLDER:
            return JobReliabilityPolicy(
                auto_retry=True,
                manual_retry=True,
                retry_backoff_seconds=max(0.0, settings.job_audit_export_retry_backoff_seconds),
            )
        if job_type == JobType.AUDIT_INTEGRITY_CHECKPOINT_PLACEHOLDER:
            return JobReliabilityPolicy(
                auto_retry=True,
                manual_retry=True,
                retry_backoff_seconds=max(
                    0.0,
                    settings.job_audit_integrity_checkpoint_retry_backoff_seconds,
                ),
            )
        if job_type == JobType.RETENTION_PURGE_PLACEHOLDER:
            return JobReliabilityPolicy(
                auto_retry=True,
                manual_retry=True,
                retry_backoff_seconds=max(0.0, settings.job_retention_retry_backoff_seconds),
            )
        if job_type in {
            JobType.AUDIT_INTEGRITY_VERIFY_PLACEHOLDER,
            JobType.CONNECTOR_HEALTH_CHECK_PLACEHOLDER,
        }:
            return JobReliabilityPolicy(
                auto_retry=False,
                manual_retry=True,
                retry_backoff_seconds=0.0,
            )
        return JobReliabilityPolicy(
            auto_retry=False,
            manual_retry=False,
            retry_backoff_seconds=0.0,
        )

    def _claimant_id(self, worker_id: str | None) -> str:
        normalized = str(worker_id or "").strip()
        return normalized or "inline"

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

    def _is_postgresql(self, db: Session) -> bool:
        return bool(db.bind and db.bind.dialect.name == "postgresql")

    def _normalize_datetime(self, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
