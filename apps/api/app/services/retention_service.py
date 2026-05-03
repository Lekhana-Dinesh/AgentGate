from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.enums import AuditActorType, JobType, PayloadRetentionClass
from app.core.metrics import get_metrics_registry
from app.core.retention import (
    PAYLOAD_REDACTION_STATUS_PROTECTED,
    PAYLOAD_REDACTION_STATUS_PURGED,
    PAYLOAD_REDACTION_STATUS_PURGE_FAILED,
    build_purged_execution_payload,
    effective_payload_expiry,
    is_purged_execution_payload,
    normalize_datetime,
    normalize_retention_class,
)
from app.models import Job, ToolCall, User
from app.models.base import utcnow
from app.services.audit_service import AuditService
from app.services.job_service import JobProcessingError, JobService

RETENTION_PURGE_QUEUED_EVENT = "retention.purge.queued"
RETENTION_PURGE_COMPLETED_EVENT = "retention.purge.completed"
RETENTION_PURGE_DRY_RUN_COMPLETED_EVENT = "retention.purge.dry_run.completed"
RETENTION_PAYLOAD_PURGED_EVENT = "retention.payload.purged"
RETENTION_PAYLOAD_PURGE_FAILED_EVENT = "retention.payload.purge_failed"


@dataclass(slots=True)
class RetentionPurgeFilters:
    retention_classes: list[str] = field(default_factory=list)
    tool_name: str | None = None
    tool_call_ids: list[str] = field(default_factory=list)
    limit: int = 100

    def normalized_retention_classes(self) -> list[str]:
        values = [normalize_retention_class(item) for item in self.retention_classes if str(item).strip()]
        return list(dict.fromkeys(values))

    def to_payload(self) -> dict:
        return {
            "retention_classes": self.normalized_retention_classes(),
            "tool_name": self.tool_name,
            "tool_call_ids": list(dict.fromkeys(self.tool_call_ids)),
            "limit": self.limit,
        }


@dataclass(slots=True)
class RetentionStatusSummary:
    eligible: int
    purged: int
    legal_hold: int
    failed: int
    protected_active: int

    def to_payload(self) -> dict[str, int]:
        return {
            "eligible": self.eligible,
            "purged": self.purged,
            "legal_hold": self.legal_hold,
            "failed": self.failed,
            "protected_active": self.protected_active,
        }


@dataclass(slots=True)
class RetentionPurgeResult:
    dry_run: bool
    requested: int
    eligible: int
    purged: int
    skipped_non_expired: int
    skipped_legal_hold: int
    already_purged: int
    failed: int
    tool_call_ids: list[str] = field(default_factory=list)
    failed_tool_call_ids: list[str] = field(default_factory=list)

    def to_payload(self) -> dict:
        return {
            "dry_run": self.dry_run,
            "requested": self.requested,
            "eligible": self.eligible,
            "purged": self.purged,
            "skipped_non_expired": self.skipped_non_expired,
            "skipped_legal_hold": self.skipped_legal_hold,
            "already_purged": self.already_purged,
            "failed": self.failed,
            "tool_call_ids": self.tool_call_ids,
            "failed_tool_call_ids": self.failed_tool_call_ids,
        }


class RetentionService:
    def __init__(self) -> None:
        self.audit_service = AuditService()
        self.job_service = JobService()
        self.metrics = get_metrics_registry()

    def enqueue_purge_job(
        self,
        db: Session,
        *,
        tenant_id: str,
        requested_by: User,
        dry_run: bool,
        filters: RetentionPurgeFilters,
        ip_address: str | None,
    ) -> Job:
        job = self.job_service.enqueue(
            db,
            tenant_id=tenant_id,
            job_type=JobType.RETENTION_PURGE_PLACEHOLDER,
            idempotency_key=f"retention_purge.placeholder:{tenant_id}:{uuid4()}",
            payload={
                "dry_run": dry_run,
                "filters": filters.to_payload(),
                "requested_by_user_id": requested_by.id,
                "requested_by_role": requested_by.role.value,
                "ip_address": ip_address,
            },
            max_attempts=max(1, get_settings().job_retention_max_attempts),
        )
        self.audit_service.create_event(
            db,
            tenant_id=tenant_id,
            actor_type=AuditActorType.USER,
            actor_id=requested_by.id,
            event_type=RETENTION_PURGE_QUEUED_EVENT,
            resource_type="job",
            resource_id=job.id,
            metadata={
                "dry_run": dry_run,
                "job_id": job.id,
                "filters": filters.to_payload(),
            },
            ip_address=ip_address,
        )
        return job

    def get_status_summary(
        self,
        db: Session,
        *,
        tenant_id: str,
        filters: RetentionPurgeFilters | None = None,
        now: datetime | None = None,
    ) -> RetentionStatusSummary:
        effective_now = normalize_datetime(now or utcnow())
        tool_calls = self._list_matching_tool_calls(db, tenant_id=tenant_id, filters=filters)

        eligible = 0
        purged = 0
        legal_hold = 0
        failed = 0
        protected_active = 0

        for tool_call in tool_calls:
            if not self._has_protected_payload(tool_call):
                continue
            normalized_class = normalize_retention_class(tool_call.payload_retention_class)
            if normalized_class == PayloadRetentionClass.LEGAL_HOLD.value:
                legal_hold += 1
                continue
            if tool_call.payload_redaction_status == PAYLOAD_REDACTION_STATUS_PURGED:
                purged += 1
                continue
            if tool_call.payload_redaction_status == PAYLOAD_REDACTION_STATUS_PURGE_FAILED:
                failed += 1
            if self._is_expired(tool_call, now=effective_now):
                eligible += 1
            else:
                protected_active += 1

        return RetentionStatusSummary(
            eligible=eligible,
            purged=purged,
            legal_hold=legal_hold,
            failed=failed,
            protected_active=protected_active,
        )

    def handle_retention_purge_job(self, db: Session, *, job: Job) -> None:
        payload = job.payload or {}
        filters_payload = payload.get("filters") or {}
        dry_run = bool(payload.get("dry_run", False))
        ip_address = str(payload.get("ip_address") or "").strip() or None
        requested_by_user_id = str(payload.get("requested_by_user_id") or "").strip() or None
        if not isinstance(filters_payload, dict):
            raise JobProcessingError(
                detail="Retention purge job payload is invalid.",
                code="retention_purge_job_invalid",
                retryable=False,
            )

        filters = RetentionPurgeFilters(
            retention_classes=[str(item) for item in (filters_payload.get("retention_classes") or [])],
            tool_name=str(filters_payload.get("tool_name") or "").strip() or None,
            tool_call_ids=[str(item) for item in (filters_payload.get("tool_call_ids") or []) if str(item).strip()],
            limit=max(1, int(filters_payload.get("limit") or 100)),
        )
        result = self.run_purge(
            db,
            tenant_id=job.tenant_id,
            dry_run=dry_run,
            filters=filters,
            job_id=job.id,
            requested_by_user_id=requested_by_user_id,
            ip_address=ip_address,
        )
        job.payload = {
            **payload,
            "filters": filters.to_payload(),
            "result": result.to_payload(),
        }

    def run_purge(
        self,
        db: Session,
        *,
        tenant_id: str,
        dry_run: bool,
        filters: RetentionPurgeFilters,
        job_id: str | None,
        requested_by_user_id: str | None,
        ip_address: str | None,
        now: datetime | None = None,
    ) -> RetentionPurgeResult:
        effective_now = normalize_datetime(now or utcnow())
        requested = 0
        eligible = 0
        purged = 0
        skipped_non_expired = 0
        skipped_legal_hold = 0
        already_purged = 0
        failed = 0
        purged_ids: list[str] = []
        failed_ids: list[str] = []

        for tool_call in self._list_matching_tool_calls(db, tenant_id=tenant_id, filters=filters):
            if requested >= filters.limit:
                break
            if not self._has_protected_payload(tool_call):
                continue
            requested += 1
            normalized_class = normalize_retention_class(tool_call.payload_retention_class)
            if normalized_class == PayloadRetentionClass.LEGAL_HOLD.value:
                skipped_legal_hold += 1
                continue
            if tool_call.payload_redaction_status == PAYLOAD_REDACTION_STATUS_PURGED or is_purged_execution_payload(
                (tool_call.request_payload or {}).get("execution_arguments")
            ):
                already_purged += 1
                continue
            if not self._is_expired(tool_call, now=effective_now):
                skipped_non_expired += 1
                continue

            eligible += 1
            if dry_run:
                purged_ids.append(tool_call.id)
                continue

            try:
                self._purge_tool_call(
                    db,
                    tool_call=tool_call,
                    job_id=job_id,
                    requested_by_user_id=requested_by_user_id,
                    ip_address=ip_address,
                    purged_at=effective_now,
                )
                purged += 1
                purged_ids.append(tool_call.id)
            except Exception:
                tool_call.payload_redaction_status = PAYLOAD_REDACTION_STATUS_PURGE_FAILED
                failed += 1
                failed_ids.append(tool_call.id)
                self.audit_service.create_event(
                    db,
                    tenant_id=tenant_id,
                    actor_type=AuditActorType.SYSTEM,
                    actor_id=None,
                    event_type=RETENTION_PAYLOAD_PURGE_FAILED_EVENT,
                    resource_type="tool_call",
                    resource_id=tool_call.id,
                    metadata={
                        "job_id": job_id,
                        "requested_by_user_id": requested_by_user_id,
                    },
                    ip_address=ip_address,
                )

        completion_event = (
            RETENTION_PURGE_DRY_RUN_COMPLETED_EVENT if dry_run else RETENTION_PURGE_COMPLETED_EVENT
        )
        self.audit_service.create_event(
            db,
            tenant_id=tenant_id,
            actor_type=AuditActorType.SYSTEM,
            actor_id=None,
            event_type=completion_event,
            resource_type="job" if job_id else "retention_purge",
            resource_id=job_id,
            metadata={
                "dry_run": dry_run,
                "requested_by_user_id": requested_by_user_id,
                "filters": filters.to_payload(),
                "result": {
                    "requested": requested,
                    "eligible": eligible,
                    "purged": purged,
                    "failed": failed,
                    "already_purged": already_purged,
                    "skipped_non_expired": skipped_non_expired,
                    "skipped_legal_hold": skipped_legal_hold,
                },
            },
            ip_address=ip_address,
        )
        self.metrics.increment("agentgate_retention_purge_runs_total", dry_run=str(dry_run).lower())
        if purged:
            self.metrics.increment("agentgate_retention_purged_total", amount=purged)
        return RetentionPurgeResult(
            dry_run=dry_run,
            requested=requested,
            eligible=eligible,
            purged=purged,
            skipped_non_expired=skipped_non_expired,
            skipped_legal_hold=skipped_legal_hold,
            already_purged=already_purged,
            failed=failed,
            tool_call_ids=purged_ids,
            failed_tool_call_ids=failed_ids,
        )

    def get_job_result(self, db: Session, *, job_id: str, tenant_id: str) -> dict | None:
        job = self.job_service.get_job(db, job_id=job_id, tenant_id=tenant_id)
        if not job:
            return None
        payload = job.payload or {}
        result = payload.get("result")
        if not isinstance(result, dict):
            return None
        return result

    def _list_matching_tool_calls(
        self,
        db: Session,
        *,
        tenant_id: str,
        filters: RetentionPurgeFilters | None,
    ) -> list[ToolCall]:
        query = select(ToolCall).where(ToolCall.tenant_id == tenant_id).order_by(ToolCall.created_at.asc())
        if filters and filters.tool_name:
            query = query.where(ToolCall.tool_name == filters.tool_name)
        if filters and filters.tool_call_ids:
            query = query.where(ToolCall.id.in_(list(dict.fromkeys(filters.tool_call_ids))))

        tool_calls = list(db.scalars(query))
        if not filters or not filters.retention_classes:
            return tool_calls

        allowed = set(filters.normalized_retention_classes())
        return [tool_call for tool_call in tool_calls if normalize_retention_class(tool_call.payload_retention_class) in allowed]

    def _has_protected_payload(self, tool_call: ToolCall) -> bool:
        request_payload = tool_call.request_payload or {}
        execution_arguments = request_payload.get("execution_arguments")
        return bool(tool_call.payload_protection_version or execution_arguments) and tool_call.payload_redaction_status in {
            PAYLOAD_REDACTION_STATUS_PROTECTED,
            PAYLOAD_REDACTION_STATUS_PURGED,
            PAYLOAD_REDACTION_STATUS_PURGE_FAILED,
        }

    def _is_expired(self, tool_call: ToolCall, *, now: datetime) -> bool:
        expires_at = effective_payload_expiry(
            tool_call.payload_retention_class,
            payload_expires_at=tool_call.payload_expires_at,
            created_at=tool_call.created_at,
        )
        if expires_at is None:
            return False
        return normalize_datetime(expires_at) <= now

    def _purge_tool_call(
        self,
        db: Session,
        *,
        tool_call: ToolCall,
        job_id: str | None,
        requested_by_user_id: str | None,
        ip_address: str | None,
        purged_at: datetime,
    ) -> None:
        request_payload = dict(tool_call.request_payload or {})
        request_payload["execution_arguments"] = build_purged_execution_payload(
            purged_at=purged_at,
            reason="retention_expired",
        )
        tool_call.request_payload = request_payload
        tool_call.payload_redaction_status = PAYLOAD_REDACTION_STATUS_PURGED
        self.audit_service.create_event(
            db,
            tenant_id=tool_call.tenant_id,
            actor_type=AuditActorType.SYSTEM,
            actor_id=None,
            event_type=RETENTION_PAYLOAD_PURGED_EVENT,
            resource_type="tool_call",
            resource_id=tool_call.id,
            metadata={
                "job_id": job_id,
                "requested_by_user_id": requested_by_user_id,
                "payload_retention_class": normalize_retention_class(tool_call.payload_retention_class),
                "payload_expires_at": (
                    effective_payload_expiry(
                        tool_call.payload_retention_class,
                        payload_expires_at=tool_call.payload_expires_at,
                        created_at=tool_call.created_at,
                    ).isoformat()
                    if effective_payload_expiry(
                        tool_call.payload_retention_class,
                        payload_expires_at=tool_call.payload_expires_at,
                        created_at=tool_call.created_at,
                    )
                    else None
                ),
                "purged_at": purged_at.isoformat(),
            },
            ip_address=ip_address,
        )
