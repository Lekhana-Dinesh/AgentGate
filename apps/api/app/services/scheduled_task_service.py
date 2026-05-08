from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy import Select, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.enums import (
    AuditActorType,
    JobStatus,
    ScheduledTaskScheduleKind,
    ScheduledTaskType,
)
from app.core.errors import AppError
from app.core.metrics import get_metrics_registry
from app.core.redaction import redact_sensitive_string
from app.models import AuditExportConfig, Job, ScheduledTask, Tool
from app.models.base import utcnow
from app.schemas.scheduled_task import (
    ScheduledAuditExportConfig,
    ScheduledAuditIntegrityCheckpointConfig,
    ScheduledAuditIntegrityVerifyConfig,
    ScheduledConnectorHealthCheckConfig,
    ScheduledRetentionPurgeConfig,
    ScheduledTaskCreate,
    ScheduledTaskResponse,
    ScheduledTaskUpdate,
)
from app.services.audit_export_service import AuditExportService
from app.services.audit_integrity_checkpoint_service import AuditIntegrityCheckpointService
from app.services.audit_integrity_service import AuditIntegrityService
from app.services.audit_service import AuditService
from app.services.job_service import JobService
from app.services.payload_service import PayloadService
from app.services.retention_service import RetentionService
from app.services.tool_health_service import ToolHealthService

SCHEDULED_TASK_CREATED_EVENT = "scheduled_task.created"
SCHEDULED_TASK_UPDATED_EVENT = "scheduled_task.updated"
SCHEDULED_TASK_RUN_ENQUEUED_EVENT = "scheduled_task.run.enqueued"
SCHEDULED_TASK_RUN_DUPLICATE_EVENT = "scheduled_task.run.duplicate"
SCHEDULED_TASK_RUN_FAILED_EVENT = "scheduled_task.run.failed"

SCHEDULED_TASK_STATUS_IDLE = "idle"
SCHEDULED_TASK_STATUS_ENQUEUED = "enqueued"
SCHEDULED_TASK_STATUS_DUPLICATE = "duplicate"
SCHEDULED_TASK_STATUS_FAILED = "failed"


@dataclass(slots=True)
class ScheduledTaskDispatchResult:
    job: Job
    status: str
    created: bool


def _normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _minute_floor(value: datetime) -> datetime:
    normalized = _normalize_datetime(value)
    return normalized.replace(second=0, microsecond=0)


def _parse_cron_expression(expression: str) -> dict[str, set[int]]:
    normalized = str(expression or "").strip()
    parts = normalized.split()
    if len(parts) != 5:
        raise AppError(
            "cron_expression must use five UTC fields: minute hour day_of_month month day_of_week.",
            status_code=400,
            code="scheduled_task_cron_invalid",
        )
    minute, hour, day, month, weekday = parts
    return {
        "minute": _expand_cron_field(minute, minimum=0, maximum=59, name="minute"),
        "hour": _expand_cron_field(hour, minimum=0, maximum=23, name="hour"),
        "day": _expand_cron_field(day, minimum=1, maximum=31, name="day_of_month"),
        "month": _expand_cron_field(month, minimum=1, maximum=12, name="month"),
        "weekday": _expand_cron_field(weekday, minimum=0, maximum=6, name="day_of_week"),
    }


def _expand_cron_field(value: str, *, minimum: int, maximum: int, name: str) -> set[int]:
    normalized = str(value or "").strip()
    if not normalized:
        raise AppError(
            f"cron_expression field {name} is empty.",
            status_code=400,
            code="scheduled_task_cron_invalid",
        )
    allowed: set[int] = set()
    for token in normalized.split(","):
        token = token.strip()
        if not token:
            continue
        step = 1
        base = token
        if "/" in token:
            base, step_token = token.split("/", 1)
            try:
                step = int(step_token)
            except ValueError as exc:
                raise AppError(
                    f"cron_expression field {name} has an invalid step value.",
                    status_code=400,
                    code="scheduled_task_cron_invalid",
                ) from exc
            if step <= 0:
                raise AppError(
                    f"cron_expression field {name} step must be positive.",
                    status_code=400,
                    code="scheduled_task_cron_invalid",
                )
        if base == "*":
            allowed.update(range(minimum, maximum + 1, step))
            continue
        if "-" in base:
            start_token, end_token = base.split("-", 1)
            try:
                start = int(start_token)
                end = int(end_token)
            except ValueError as exc:
                raise AppError(
                    f"cron_expression field {name} has an invalid range.",
                    status_code=400,
                    code="scheduled_task_cron_invalid",
                ) from exc
            if start > end:
                raise AppError(
                    f"cron_expression field {name} range must be ascending.",
                    status_code=400,
                    code="scheduled_task_cron_invalid",
                )
            _validate_cron_number(start, minimum=minimum, maximum=maximum, name=name)
            _validate_cron_number(end, minimum=minimum, maximum=maximum, name=name)
            allowed.update(range(start, end + 1, step))
            continue
        try:
            number = int(base)
        except ValueError as exc:
            raise AppError(
                f"cron_expression field {name} has an invalid value.",
                status_code=400,
                code="scheduled_task_cron_invalid",
            ) from exc
        _validate_cron_number(number, minimum=minimum, maximum=maximum, name=name)
        allowed.add(number)
    if not allowed:
        raise AppError(
            f"cron_expression field {name} produced no matching values.",
            status_code=400,
            code="scheduled_task_cron_invalid",
        )
    return allowed


def _validate_cron_number(value: int, *, minimum: int, maximum: int, name: str) -> None:
    if value < minimum or value > maximum:
        raise AppError(
            f"cron_expression field {name} must stay between {minimum} and {maximum}.",
            status_code=400,
            code="scheduled_task_cron_invalid",
        )


def _next_cron_occurrence(expression: str, *, after: datetime) -> datetime:
    parsed = _parse_cron_expression(expression)
    candidate = _minute_floor(after) + timedelta(minutes=1)
    max_attempts = 366 * 24 * 60
    for _ in range(max_attempts):
        if (
            candidate.minute in parsed["minute"]
            and candidate.hour in parsed["hour"]
            and candidate.day in parsed["day"]
            and candidate.month in parsed["month"]
            and candidate.weekday() in parsed["weekday"]
        ):
            return candidate
        candidate += timedelta(minutes=1)
    raise AppError(
        "cron_expression did not produce a future run inside the supported search window.",
        status_code=400,
        code="scheduled_task_cron_invalid",
    )


class ScheduledTaskService:
    def __init__(self) -> None:
        self.audit_service = AuditService()
        self.audit_export_service = AuditExportService()
        self.audit_integrity_checkpoint_service = AuditIntegrityCheckpointService()
        self.audit_integrity_service = AuditIntegrityService()
        self.job_service = JobService()
        self.payload_service = PayloadService()
        self.retention_service = RetentionService()
        self.tool_health_service = ToolHealthService()
        self.metrics = get_metrics_registry()

    def list_tasks(self, db: Session, *, tenant_id: str) -> list[ScheduledTaskResponse]:
        tasks = list(
            db.scalars(
                select(ScheduledTask)
                .where(ScheduledTask.tenant_id == tenant_id)
                .order_by(ScheduledTask.created_at.desc())
            )
        )
        return [self.serialize_task(task) for task in tasks]

    def get_task_or_raise(self, db: Session, *, tenant_id: str, task_id: str) -> ScheduledTask:
        task = db.scalar(
            select(ScheduledTask).where(
                ScheduledTask.id == task_id,
                ScheduledTask.tenant_id == tenant_id,
            )
        )
        if not task:
            raise AppError("Scheduled task not found.", status_code=404, code="scheduled_task_not_found")
        return task

    def create_task(
        self,
        db: Session,
        *,
        tenant_id: str,
        payload: ScheduledTaskCreate,
        actor_type: AuditActorType,
        actor_id: str | None,
        ip_address: str | None,
    ) -> ScheduledTask:
        normalized_config = self._normalize_task_config(
            db,
            tenant_id=tenant_id,
            task_type=payload.task_type,
            config=payload.config,
        )
        next_run_at = payload.next_run_at or self._first_run_at(
            schedule_kind=payload.schedule_kind,
            interval_seconds=payload.interval_seconds,
            cron_expression=payload.cron_expression,
            base_time=utcnow(),
        )
        task = ScheduledTask(
            tenant_id=tenant_id,
            name=payload.name,
            task_type=payload.task_type,
            enabled=payload.enabled,
            schedule_kind=payload.schedule_kind,
            interval_seconds=payload.interval_seconds,
            cron_expression=payload.cron_expression,
            next_run_at=_normalize_datetime(next_run_at),
            last_run_at=None,
            last_status=SCHEDULED_TASK_STATUS_IDLE,
            last_error=None,
            idempotency_key=f"scheduled_task:{uuid4().hex}",
            config=normalized_config,
        )
        db.add(task)
        db.flush()
        self.audit_service.create_event(
            db,
            tenant_id=tenant_id,
            actor_type=actor_type,
            actor_id=actor_id,
            event_type=SCHEDULED_TASK_CREATED_EVENT,
            resource_type="scheduled_task",
            resource_id=task.id,
            metadata={
                "task_type": task.task_type.value,
                "schedule_kind": task.schedule_kind.value,
                "enabled": task.enabled,
            },
            ip_address=ip_address,
        )
        return task

    def update_task(
        self,
        db: Session,
        *,
        tenant_id: str,
        task_id: str,
        payload: ScheduledTaskUpdate,
        actor_type: AuditActorType,
        actor_id: str | None,
        ip_address: str | None,
    ) -> ScheduledTask:
        task = self.get_task_or_raise(db, tenant_id=tenant_id, task_id=task_id)
        updates = payload.model_dump(exclude_unset=True)
        merged = {
            "name": task.name,
            "task_type": task.task_type,
            "enabled": task.enabled,
            "schedule_kind": task.schedule_kind,
            "interval_seconds": task.interval_seconds,
            "cron_expression": task.cron_expression,
            "next_run_at": task.next_run_at,
            "config": dict(task.config or {}),
        }
        merged.update(updates)
        validated = ScheduledTaskCreate.model_validate(merged)
        normalized_config = self._normalize_task_config(
            db,
            tenant_id=tenant_id,
            task_type=task.task_type,
            config=validated.config,
        )
        task.name = validated.name
        task.enabled = validated.enabled
        task.schedule_kind = validated.schedule_kind
        task.interval_seconds = validated.interval_seconds
        task.cron_expression = validated.cron_expression
        task.config = normalized_config
        schedule_fields_changed = bool(
            {"schedule_kind", "interval_seconds", "cron_expression"} & set(updates.keys())
        )
        if "next_run_at" in updates and validated.next_run_at is not None:
            task.next_run_at = _normalize_datetime(validated.next_run_at)
        elif schedule_fields_changed:
            task.next_run_at = self._first_run_at(
                schedule_kind=validated.schedule_kind,
                interval_seconds=validated.interval_seconds,
                cron_expression=validated.cron_expression,
                base_time=utcnow(),
            )
        self.audit_service.create_event(
            db,
            tenant_id=tenant_id,
            actor_type=actor_type,
            actor_id=actor_id,
            event_type=SCHEDULED_TASK_UPDATED_EVENT,
            resource_type="scheduled_task",
            resource_id=task.id,
            metadata={"updated_fields": sorted(updates.keys())},
            ip_address=ip_address,
        )
        return task

    def run_now(
        self,
        db: Session,
        *,
        tenant_id: str,
        task_id: str,
        actor_type: AuditActorType,
        actor_id: str | None,
        ip_address: str | None,
    ) -> ScheduledTaskDispatchResult:
        task = self.get_task_or_raise(db, tenant_id=tenant_id, task_id=task_id)
        return self._dispatch_task(
            db,
            task=task,
            scheduled_for=utcnow(),
            trigger="manual",
            actor_type=actor_type,
            actor_id=actor_id,
            ip_address=ip_address,
            advance_schedule=False,
        )

    def process_due_tasks(
        self,
        *,
        session_factory: sessionmaker,
        limit: int,
        scheduler_id: str,
    ) -> int:
        processed = 0
        for _ in range(max(1, limit)):
            with session_factory() as db:
                try:
                    result = self._claim_and_dispatch_next_due_task(
                        db,
                        scheduler_id=scheduler_id,
                    )
                    if result is None:
                        break
                    if result.created:
                        self.job_service.dispatch_after_commit(
                            db,
                            job_id=result.job.id,
                            raise_on_error=False,
                        )
                    processed += 1
                except AppError:
                    processed += 1
        return processed

    def serialize_task(self, task: ScheduledTask) -> ScheduledTaskResponse:
        return ScheduledTaskResponse(
            id=task.id,
            tenant_id=task.tenant_id,
            name=task.name,
            task_type=task.task_type,
            enabled=task.enabled,
            schedule_kind=task.schedule_kind,
            interval_seconds=task.interval_seconds,
            cron_expression=task.cron_expression,
            next_run_at=task.next_run_at,
            last_run_at=task.last_run_at,
            last_status=task.last_status,
            last_error=task.last_error,
            idempotency_key=task.idempotency_key,
            config=self.payload_service.sanitize_payload(task.config or {}),
            created_at=task.created_at,
            updated_at=task.updated_at,
        )

    def _claim_and_dispatch_next_due_task(
        self,
        db: Session,
        *,
        scheduler_id: str,
    ) -> ScheduledTaskDispatchResult | None:
        now = utcnow()
        query: Select[tuple[ScheduledTask]] = (
            select(ScheduledTask)
            .where(
                ScheduledTask.enabled.is_(True),
                ScheduledTask.next_run_at <= now,
            )
            .order_by(ScheduledTask.next_run_at.asc(), ScheduledTask.created_at.asc())
            .limit(1)
        )
        if self._is_postgresql(db):
            query = query.with_for_update(skip_locked=True)
        task = db.scalar(query)
        if not task:
            return None
        if _normalize_datetime(task.next_run_at) > now:
            return None
        return self._dispatch_task(
            db,
            task=task,
            scheduled_for=task.next_run_at,
            trigger="scheduled",
            actor_type=AuditActorType.SYSTEM,
            actor_id=None,
            ip_address=None,
            advance_schedule=True,
            scheduler_id=scheduler_id,
        )

    def _dispatch_task(
        self,
        db: Session,
        *,
        task: ScheduledTask,
        scheduled_for: datetime,
        trigger: str,
        actor_type: AuditActorType,
        actor_id: str | None,
        ip_address: str | None,
        advance_schedule: bool,
        scheduler_id: str | None = None,
    ) -> ScheduledTaskDispatchResult:
        now = utcnow()
        try:
            result = self._enqueue_for_task(
                db,
                task=task,
                scheduled_for=scheduled_for,
                trigger=trigger,
                actor_type=actor_type,
                actor_id=actor_id,
                ip_address=ip_address,
            )
            task.last_run_at = now
            task.last_status = result.status
            task.last_error = None
            if advance_schedule:
                task.next_run_at = self._advance_next_run_at(task, now=now)
            self.audit_service.create_event(
                db,
                tenant_id=task.tenant_id,
                actor_type=actor_type,
                actor_id=actor_id,
                event_type=(
                    SCHEDULED_TASK_RUN_DUPLICATE_EVENT
                    if result.status == SCHEDULED_TASK_STATUS_DUPLICATE
                    else SCHEDULED_TASK_RUN_ENQUEUED_EVENT
                ),
                resource_type="scheduled_task",
                resource_id=task.id,
                metadata={
                    "task_type": task.task_type.value,
                    "job_id": result.job.id,
                    "trigger": trigger,
                    "scheduler_id": scheduler_id,
                    "status": result.status,
                    "created": result.created,
                },
                ip_address=ip_address,
            )
            db.commit()
            if result.created:
                self.metrics.increment(
                    "agentgate_scheduler_enqueues_total",
                    task_type=task.task_type.value,
                    trigger=trigger,
                )
            return result
        except AppError as exc:
            detail = redact_sensitive_string(exc.detail)
            task.last_run_at = now
            task.last_status = SCHEDULED_TASK_STATUS_FAILED
            task.last_error = detail
            if advance_schedule:
                task.next_run_at = self._advance_next_run_at(task, now=now)
            self.audit_service.create_event(
                db,
                tenant_id=task.tenant_id,
                actor_type=actor_type,
                actor_id=actor_id,
                event_type=SCHEDULED_TASK_RUN_FAILED_EVENT,
                resource_type="scheduled_task",
                resource_id=task.id,
                metadata={
                    "task_type": task.task_type.value,
                    "trigger": trigger,
                    "scheduler_id": scheduler_id,
                    "error_code": exc.code,
                    "detail": detail,
                },
                ip_address=ip_address,
            )
            db.commit()
            self.metrics.increment(
                "agentgate_scheduler_errors_total",
                task_type=task.task_type.value,
                trigger=trigger,
                error_code=exc.code,
            )
            raise

    def _enqueue_for_task(
        self,
        db: Session,
        *,
        task: ScheduledTask,
        scheduled_for: datetime,
        trigger: str,
        actor_type: AuditActorType,
        actor_id: str | None,
        ip_address: str | None,
    ) -> ScheduledTaskDispatchResult:
        inflight = self._find_inflight_job(db, task=task)
        if inflight is not None:
            return ScheduledTaskDispatchResult(
                job=inflight,
                status=SCHEDULED_TASK_STATUS_DUPLICATE,
                created=False,
            )

        idempotency_key = self._run_idempotency_key(
            task=task,
            trigger=trigger,
            scheduled_for=scheduled_for,
        )
        if task.task_type == ScheduledTaskType.RETENTION_PURGE:
            config = self._validate_config_model(
                ScheduledRetentionPurgeConfig,
                task.config,
                error_code="scheduled_task_retention_config_invalid",
                status_code=400,
            )
            job = self.retention_service.enqueue_purge_job(
                db,
                tenant_id=task.tenant_id,
                requested_by=None,
                dry_run=config.dry_run,
                filters=self.retention_service.build_filters_from_scheduled_config(config),
                ip_address=ip_address,
                actor_type=actor_type,
                actor_id=actor_id,
                idempotency_key=idempotency_key,
                source=trigger,
                scheduled_task_id=task.id,
            )
            return ScheduledTaskDispatchResult(job=job, status=SCHEDULED_TASK_STATUS_ENQUEUED, created=True)
        if task.task_type == ScheduledTaskType.AUDIT_EXPORT:
            config = self._validate_config_model(
                ScheduledAuditExportConfig,
                task.config,
                error_code="scheduled_task_audit_export_config_invalid",
                status_code=400,
            )
            export_config = self.audit_export_service.get_config_or_raise(
                db,
                tenant_id=task.tenant_id,
                config_id=config.audit_export_config_id,
            )
            job = self.audit_export_service.enqueue_run(
                db,
                config=export_config,
                requested_by=None,
                dry_run=config.dry_run,
                ip_address=ip_address,
                actor_type=actor_type,
                actor_id=actor_id,
                idempotency_key=idempotency_key,
                source=trigger,
                scheduled_task_id=task.id,
            )
            created = job.idempotency_key == idempotency_key
            return ScheduledTaskDispatchResult(
                job=job,
                status=SCHEDULED_TASK_STATUS_ENQUEUED if created else SCHEDULED_TASK_STATUS_DUPLICATE,
                created=created,
            )
        if task.task_type == ScheduledTaskType.AUDIT_INTEGRITY_VERIFY:
            config = self._validate_config_model(
                ScheduledAuditIntegrityVerifyConfig,
                task.config,
                error_code="scheduled_task_audit_integrity_config_invalid",
                status_code=400,
            )
            job = self.audit_integrity_service.enqueue_verify_job(
                db,
                tenant_id=task.tenant_id,
                bounds=self.audit_integrity_service.build_bounds_from_scheduled_config(config),
                actor_type=actor_type,
                actor_id=actor_id,
                ip_address=ip_address,
                idempotency_key=idempotency_key,
                source=trigger,
                scheduled_task_id=task.id,
            )
            return ScheduledTaskDispatchResult(job=job, status=SCHEDULED_TASK_STATUS_ENQUEUED, created=True)
        if task.task_type == ScheduledTaskType.AUDIT_INTEGRITY_CHECKPOINT:
            self._validate_config_model(
                ScheduledAuditIntegrityCheckpointConfig,
                task.config,
                error_code="scheduled_task_audit_integrity_checkpoint_config_invalid",
                status_code=400,
            )
            job = self.audit_integrity_checkpoint_service.enqueue_checkpoint_job(
                db,
                tenant_id=task.tenant_id,
                requested_by=None,
                ip_address=ip_address,
                actor_type=actor_type,
                actor_id=actor_id,
                idempotency_key=idempotency_key,
                source=trigger,
                scheduled_task_id=task.id,
            )
            return ScheduledTaskDispatchResult(job=job, status=SCHEDULED_TASK_STATUS_ENQUEUED, created=True)
        if task.task_type == ScheduledTaskType.CONNECTOR_HEALTH_CHECK:
            config = self._validate_config_model(
                ScheduledConnectorHealthCheckConfig,
                task.config,
                error_code="scheduled_task_connector_health_config_invalid",
                status_code=400,
            )
            job = self.tool_health_service.enqueue_connector_health_check_job(
                db,
                tenant_id=task.tenant_id,
                config=config,
                actor_type=actor_type,
                actor_id=actor_id,
                ip_address=ip_address,
                idempotency_key=idempotency_key,
                source=trigger,
                scheduled_task_id=task.id,
            )
            return ScheduledTaskDispatchResult(job=job, status=SCHEDULED_TASK_STATUS_ENQUEUED, created=True)
        raise AppError(
            "Scheduled task type is not supported in this build.",
            status_code=400,
            code="scheduled_task_type_unsupported",
        )

    def _normalize_task_config(
        self,
        db: Session,
        *,
        tenant_id: str,
        task_type: ScheduledTaskType,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        if task_type == ScheduledTaskType.RETENTION_PURGE:
            scheduled_config = self._validate_config_model(
                ScheduledRetentionPurgeConfig,
                config,
                error_code="scheduled_task_retention_config_invalid",
                status_code=422,
            )
            if scheduled_config.tool_name:
                tool = db.scalar(
                    select(Tool).where(
                        Tool.tenant_id == tenant_id,
                        Tool.name == scheduled_config.tool_name,
                    )
                )
                if tool is None:
                    raise AppError(
                        "Retention task tool_name was not found in the tenant.",
                        status_code=404,
                        code="scheduled_task_tool_not_found",
                    )
            return scheduled_config.model_dump(mode="json")
        if task_type == ScheduledTaskType.AUDIT_EXPORT:
            scheduled_config = self._validate_config_model(
                ScheduledAuditExportConfig,
                config,
                error_code="scheduled_task_audit_export_config_invalid",
                status_code=422,
            )
            export_config = db.scalar(
                select(AuditExportConfig).where(
                    AuditExportConfig.id == scheduled_config.audit_export_config_id,
                    AuditExportConfig.tenant_id == tenant_id,
                )
            )
            if export_config is None:
                raise AppError(
                    "Audit export config was not found in the tenant.",
                    status_code=404,
                    code="scheduled_task_audit_export_config_not_found",
                )
            return scheduled_config.model_dump(mode="json")
        if task_type == ScheduledTaskType.AUDIT_INTEGRITY_VERIFY:
            scheduled_config = self._validate_config_model(
                ScheduledAuditIntegrityVerifyConfig,
                config,
                error_code="scheduled_task_audit_integrity_config_invalid",
                status_code=422,
            )
            return scheduled_config.model_dump(mode="json")
        if task_type == ScheduledTaskType.AUDIT_INTEGRITY_CHECKPOINT:
            scheduled_config = self._validate_config_model(
                ScheduledAuditIntegrityCheckpointConfig,
                config,
                error_code="scheduled_task_audit_integrity_checkpoint_config_invalid",
                status_code=422,
            )
            return scheduled_config.model_dump(mode="json")
        if task_type == ScheduledTaskType.CONNECTOR_HEALTH_CHECK:
            scheduled_config = self._validate_config_model(
                ScheduledConnectorHealthCheckConfig,
                config,
                error_code="scheduled_task_connector_health_config_invalid",
                status_code=422,
            )
            if scheduled_config.tool_ids:
                tools = list(
                    db.scalars(
                        select(Tool).where(
                            Tool.tenant_id == tenant_id,
                            Tool.id.in_(list(dict.fromkeys(scheduled_config.tool_ids))),
                        )
                    )
                )
                if len(tools) != len(list(dict.fromkeys(scheduled_config.tool_ids))):
                    raise AppError(
                        "One or more connector health check tool_ids were not found in the tenant.",
                        status_code=404,
                        code="scheduled_task_tool_not_found",
                    )
            return scheduled_config.model_dump(mode="json")
        raise AppError(
            "Scheduled task type is not supported in this build.",
            status_code=400,
            code="scheduled_task_type_unsupported",
        )

    def _first_run_at(
        self,
        *,
        schedule_kind: ScheduledTaskScheduleKind,
        interval_seconds: int | None,
        cron_expression: str | None,
        base_time: datetime,
    ) -> datetime:
        now = _normalize_datetime(base_time)
        if schedule_kind == ScheduledTaskScheduleKind.INTERVAL:
            assert interval_seconds is not None
            return now + timedelta(seconds=interval_seconds)
        assert cron_expression is not None
        return _next_cron_occurrence(cron_expression, after=now)

    def _advance_next_run_at(self, task: ScheduledTask, *, now: datetime) -> datetime:
        current = _normalize_datetime(task.next_run_at)
        effective_now = _normalize_datetime(now)
        if task.schedule_kind == ScheduledTaskScheduleKind.INTERVAL:
            assert task.interval_seconds is not None
            interval = timedelta(seconds=task.interval_seconds)
            next_run_at = current + interval
            while next_run_at <= effective_now:
                next_run_at += interval
            return next_run_at
        assert task.cron_expression is not None
        return _next_cron_occurrence(
            task.cron_expression,
            after=effective_now if effective_now > current else current,
        )

    def _run_idempotency_key(
        self,
        *,
        task: ScheduledTask,
        trigger: str,
        scheduled_for: datetime,
    ) -> str:
        scheduled_at = _normalize_datetime(scheduled_for).strftime("%Y%m%dT%H%M%SZ")
        return f"{task.idempotency_key}:{trigger}:{scheduled_at}"

    def _find_inflight_job(self, db: Session, *, task: ScheduledTask) -> Job | None:
        prefix = f"{task.idempotency_key}:"
        return db.scalar(
            select(Job)
            .where(
                Job.tenant_id == task.tenant_id,
                Job.idempotency_key.like(f"{prefix}%"),
                Job.status.in_((JobStatus.QUEUED, JobStatus.RUNNING)),
            )
            .order_by(Job.created_at.desc())
            .limit(1)
        )

    def _is_postgresql(self, db: Session) -> bool:
        return bool(db.bind and db.bind.dialect.name == "postgresql")

    def _validate_config_model(self, model_cls, config: dict[str, Any] | None, *, error_code: str, status_code: int):
        try:
            return model_cls.model_validate(config or {})
        except ValidationError as exc:
            raise AppError(
                "Scheduled task config is invalid.",
                status_code=status_code,
                code=error_code,
            ) from exc
