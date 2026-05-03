from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlparse

import httpx
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.enums import (
    AuditActorType,
    AuditExportDestinationType,
    AuditEventSeverity,
    JobStatus,
    JobType,
)
from app.core.errors import AppError
from app.core.metrics import get_metrics_registry
from app.core.redaction import redact_sensitive_data, redact_sensitive_string
from app.models import AuditEvent, AuditExportConfig, Job, User
from app.models.base import utcnow
from app.schemas.audit_export import (
    AuditExportConfigResponse,
    AuditExportCreate,
    AuditExportRunResult,
    AuditExportStatusResponse,
    AuditExportUpdate,
)
from app.schemas.job import serialize_job, serialize_job_summary
from app.security.secret_references import (
    SecretResolutionError,
    build_env_secret_reference,
    get_secret_resolver,
)
from app.services.audit_service import AuditService
from app.services.job_service import JobProcessingError, JobService
from app.services.payload_service import PayloadService

logger = logging.getLogger(__name__)

AUDIT_EXPORT_CONFIG_CREATED_EVENT = "audit_export.config.created"
AUDIT_EXPORT_CONFIG_UPDATED_EVENT = "audit_export.config.updated"
AUDIT_EXPORT_RUN_QUEUED_EVENT = "audit_export.run.queued"
AUDIT_EXPORT_RUN_SUCCEEDED_EVENT = "audit_export.run.succeeded"
AUDIT_EXPORT_RUN_DRY_RUN_COMPLETED_EVENT = "audit_export.run.dry_run.completed"
AUDIT_EXPORT_RUN_FAILED_EVENT = "audit_export.run.failed"
AUDIT_EXPORT_RUN_RETRY_EXHAUSTED_EVENT = "audit_export.run.retry_exhausted"

OPTIONAL_AUTH_DESTINATIONS = {
    AuditExportDestinationType.WEBHOOK,
    AuditExportDestinationType.HTTP_JSON,
    AuditExportDestinationType.CUSTOM_PLACEHOLDER,
}


@dataclass(slots=True)
class AuditExportDeliveryError(Exception):
    detail: str
    code: str
    retryable: bool

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.detail


@dataclass(frozen=True, slots=True)
class ExportableAuditEvent:
    event: AuditEvent
    severity: AuditEventSeverity
    payload: dict


class AuditExportDispatcher:
    def __init__(self, client_factory=None) -> None:
        self.client_factory = client_factory

    def send_batch(
        self,
        config: AuditExportConfig,
        *,
        batch: list[dict],
    ) -> None:
        if not batch:
            return

        destination_type = config.destination_type
        token = self._resolve_destination_token(config)
        timeout_seconds = get_settings().audit_export_timeout_seconds

        if destination_type in {
            AuditExportDestinationType.WEBHOOK,
            AuditExportDestinationType.HTTP_JSON,
            AuditExportDestinationType.CUSTOM_PLACEHOLDER,
        }:
            self._post_json(
                endpoint_url=config.endpoint_url,
                headers=self._authorization_headers(token, scheme="Bearer"),
                json_body={
                    "source": "agentgate",
                    "destination_type": destination_type.value,
                    "config_name": config.name,
                    "events": batch,
                },
                timeout_seconds=timeout_seconds,
            )
            return

        if destination_type == AuditExportDestinationType.SPLUNK_HEC:
            lines = []
            for item in batch:
                lines.append(
                    json.dumps(
                        {
                            "time": self._unix_timestamp(item.get("created_at")),
                            "source": "agentgate",
                            "sourcetype": "agentgate:audit",
                            "event": item,
                        },
                        ensure_ascii=True,
                        separators=(",", ":"),
                    )
                )
            self._post_content(
                endpoint_url=config.endpoint_url,
                headers=self._authorization_headers(token, scheme="Splunk"),
                content="\n".join(lines).encode("utf-8"),
                content_type="application/json",
                timeout_seconds=timeout_seconds,
            )
            return

        if destination_type == AuditExportDestinationType.DATADOG:
            payload = []
            for item in batch:
                payload.append(
                    {
                        "ddsource": "agentgate",
                        "service": "agentgate",
                        "message": f"{item['event_type']} {item['resource_type']}",
                        "hostname": "agentgate",
                        "timestamp": self._unix_timestamp(item.get("created_at")) * 1000,
                        "attributes": item,
                    }
                )
            headers = {"DD-API-KEY": token or "", "Content-Type": "application/json"}
            self._post_json(
                endpoint_url=config.endpoint_url,
                headers=headers,
                json_body=payload,
                timeout_seconds=timeout_seconds,
            )
            return

        raise AuditExportDeliveryError(
            detail="Audit export destination type is not supported in this build.",
            code="audit_export_destination_unsupported",
            retryable=False,
        )

    def _resolve_destination_token(self, config: AuditExportConfig) -> str | None:
        required = config.destination_type not in OPTIONAL_AUTH_DESTINATIONS
        if config.secret_ref:
            try:
                return get_secret_resolver().resolve(config.secret_ref, allow_bare_env=False).value
            except SecretResolutionError as exc:
                raise self._map_secret_resolution_error(exc) from exc

        if config.token_env_var:
            try:
                return get_secret_resolver().resolve(
                    build_env_secret_reference(config.token_env_var),
                    allow_bare_env=False,
                ).value
            except SecretResolutionError as exc:
                raise self._map_secret_resolution_error(exc) from exc

        if required:
            raise AuditExportDeliveryError(
                detail="Audit export destination credentials are not configured.",
                code="audit_export_credentials_missing",
                retryable=False,
            )
        return None

    def _map_secret_resolution_error(self, exc: SecretResolutionError) -> AuditExportDeliveryError:
        if exc.code == "invalid_secret_ref":
            return AuditExportDeliveryError(
                detail="Audit export secret reference is invalid.",
                code="audit_export_secret_ref_invalid",
                retryable=False,
            )
        if exc.code == "secret_provider_unconfigured":
            return AuditExportDeliveryError(
                detail="Audit export secret reference requires an external resolver that is not configured.",
                code="audit_export_secret_ref_unsupported",
                retryable=False,
            )
        return AuditExportDeliveryError(
            detail="Audit export destination credentials are not available in the current environment.",
            code="audit_export_credentials_missing",
            retryable=False,
        )

    def _authorization_headers(self, token: str | None, *, scheme: str) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"{scheme} {token}"
        return headers

    def _post_json(
        self,
        *,
        endpoint_url: str,
        headers: dict[str, str],
        json_body,
        timeout_seconds: float,
    ) -> None:
        try:
            with self._build_client(timeout_seconds=timeout_seconds, headers=headers) as client:
                response = client.post(endpoint_url, json=json_body)
        except httpx.TimeoutException as exc:
            raise AuditExportDeliveryError(
                detail="Audit export destination timed out.",
                code="audit_export_timeout",
                retryable=True,
            ) from exc
        except httpx.RequestError as exc:
            raise AuditExportDeliveryError(
                detail="Audit export destination is temporarily unavailable.",
                code="audit_export_network_error",
                retryable=True,
            ) from exc
        self._raise_for_response(response)

    def _post_content(
        self,
        *,
        endpoint_url: str,
        headers: dict[str, str],
        content: bytes,
        content_type: str,
        timeout_seconds: float,
    ) -> None:
        merged_headers = dict(headers)
        merged_headers["Content-Type"] = content_type
        try:
            with self._build_client(timeout_seconds=timeout_seconds, headers=merged_headers) as client:
                response = client.post(endpoint_url, content=content)
        except httpx.TimeoutException as exc:
            raise AuditExportDeliveryError(
                detail="Audit export destination timed out.",
                code="audit_export_timeout",
                retryable=True,
            ) from exc
        except httpx.RequestError as exc:
            raise AuditExportDeliveryError(
                detail="Audit export destination is temporarily unavailable.",
                code="audit_export_network_error",
                retryable=True,
            ) from exc
        self._raise_for_response(response)

    def _raise_for_response(self, response: httpx.Response) -> None:
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        message = redact_sensitive_string(
            str(payload.get("error") or payload.get("message") or "Audit export delivery failed.")
        )
        status_code = response.status_code
        if status_code < 400:
            return
        if status_code in {401, 403}:
            raise AuditExportDeliveryError(
                detail="Audit export destination rejected the configured credentials.",
                code="audit_export_auth_failed",
                retryable=False,
            )
        if status_code == 404:
            raise AuditExportDeliveryError(
                detail="Audit export endpoint was not found.",
                code="audit_export_endpoint_not_found",
                retryable=False,
            )
        if status_code == 409:
            raise AuditExportDeliveryError(
                detail=message or "Audit export destination reported a conflict.",
                code="audit_export_conflict",
                retryable=False,
            )
        if status_code == 422:
            raise AuditExportDeliveryError(
                detail=message or "Audit export payload was rejected by the destination.",
                code="audit_export_payload_invalid",
                retryable=False,
            )
        if status_code == 429:
            raise AuditExportDeliveryError(
                detail="Audit export destination rate limited the request.",
                code="audit_export_rate_limited",
                retryable=True,
            )
        if status_code >= 500:
            raise AuditExportDeliveryError(
                detail="Audit export destination is temporarily unavailable.",
                code="audit_export_upstream_unavailable",
                retryable=True,
            )
        raise AuditExportDeliveryError(
            detail=message or "Audit export delivery failed.",
            code="audit_export_request_failed",
            retryable=False,
        )

    def _build_client(self, *, timeout_seconds: float, headers: dict[str, str]) -> httpx.Client:
        if self.client_factory:
            return self.client_factory(headers=headers, timeout=timeout_seconds)
        return httpx.Client(headers=headers, timeout=timeout_seconds, follow_redirects=True)

    def _unix_timestamp(self, value) -> int:
        if isinstance(value, datetime):
            return max(0, int(value.timestamp()))
        if isinstance(value, str):
            try:
                return max(0, int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()))
            except ValueError:
                return 0
        return 0


class AuditExportService:
    def __init__(self, dispatcher: AuditExportDispatcher | None = None) -> None:
        self.audit_service = AuditService()
        self.job_service = JobService()
        self.payload_service = PayloadService()
        self.dispatcher = dispatcher or AuditExportDispatcher()
        self.metrics = get_metrics_registry()

    def list_configs(self, db: Session, *, tenant_id: str) -> list[AuditExportConfigResponse]:
        configs = list(
            db.scalars(
                select(AuditExportConfig)
                .where(AuditExportConfig.tenant_id == tenant_id)
                .order_by(AuditExportConfig.created_at.desc())
            )
        )
        return self._serialize_configs(db, configs)

    def get_config_or_raise(self, db: Session, *, tenant_id: str, config_id: str) -> AuditExportConfig:
        config = db.scalar(
            select(AuditExportConfig).where(
                AuditExportConfig.id == config_id,
                AuditExportConfig.tenant_id == tenant_id,
            )
        )
        if not config:
            raise AppError(
                "Audit export config not found.",
                status_code=404,
                code="audit_export_config_not_found",
            )
        return config

    def get_config_response(
        self,
        db: Session,
        *,
        tenant_id: str,
        config_id: str,
    ) -> AuditExportConfigResponse:
        config = self.get_config_or_raise(db, tenant_id=tenant_id, config_id=config_id)
        return self._serialize_config(db, config, last_job=self._job_for_config(db, config))

    def create_config(
        self,
        db: Session,
        *,
        tenant_id: str,
        payload: AuditExportCreate,
        current_user: User,
    ) -> AuditExportConfig:
        config = AuditExportConfig(
            tenant_id=tenant_id,
            name=payload.name,
            destination_type=payload.destination_type,
            enabled=payload.enabled,
            endpoint_url=payload.endpoint_url,
            secret_ref=payload.secret_ref,
            token_env_var=payload.token_env_var,
            event_type_filters=list(payload.event_type_filters),
            severity_filters=[item.value for item in payload.severity_filters],
            max_batch_size=payload.max_batch_size,
            last_export_status=None,
            last_error=None,
        )
        db.add(config)
        db.flush()
        self.audit_service.create_event(
            db,
            tenant_id=tenant_id,
            actor_type=AuditActorType.USER,
            actor_id=current_user.id,
            event_type=AUDIT_EXPORT_CONFIG_CREATED_EVENT,
            resource_type="audit_export_config",
            resource_id=config.id,
            metadata={
                "destination_type": config.destination_type.value,
                "enabled": config.enabled,
                "event_type_filter_count": len(config.event_type_filters or []),
                "severity_filter_count": len(config.severity_filters or []),
            },
        )
        return config

    def update_config(
        self,
        db: Session,
        *,
        tenant_id: str,
        config_id: str,
        payload: AuditExportUpdate,
        current_user: User,
    ) -> AuditExportConfig:
        config = self.get_config_or_raise(db, tenant_id=tenant_id, config_id=config_id)
        updates = payload.model_dump(exclude_unset=True)
        merged = {
            "name": config.name,
            "destination_type": config.destination_type,
            "enabled": config.enabled,
            "endpoint_url": config.endpoint_url,
            "secret_ref": config.secret_ref,
            "token_env_var": config.token_env_var,
            "event_type_filters": config.event_type_filters,
            "severity_filters": [AuditEventSeverity(item) for item in (config.severity_filters or [])],
            "max_batch_size": config.max_batch_size,
        }
        merged.update(updates)
        validated = AuditExportCreate.model_validate(merged)
        config.name = validated.name
        config.destination_type = validated.destination_type
        config.enabled = validated.enabled
        config.endpoint_url = validated.endpoint_url
        config.secret_ref = validated.secret_ref
        config.token_env_var = validated.token_env_var
        config.event_type_filters = list(validated.event_type_filters)
        config.severity_filters = [item.value for item in validated.severity_filters]
        config.max_batch_size = validated.max_batch_size
        self.audit_service.create_event(
            db,
            tenant_id=tenant_id,
            actor_type=AuditActorType.USER,
            actor_id=current_user.id,
            event_type=AUDIT_EXPORT_CONFIG_UPDATED_EVENT,
            resource_type="audit_export_config",
            resource_id=config.id,
            metadata={"updated_fields": sorted(updates.keys())},
        )
        return config

    def enqueue_run(
        self,
        db: Session,
        *,
        config: AuditExportConfig,
        requested_by: User,
        dry_run: bool,
        ip_address: str | None,
    ) -> Job:
        if not config.enabled:
            raise AppError(
                "Audit export config is disabled.",
                status_code=409,
                code="audit_export_config_disabled",
            )
        existing_job = None
        if config.last_export_job_id:
            existing_job = self.job_service.get_job(
                db,
                job_id=config.last_export_job_id,
                tenant_id=config.tenant_id,
            )
        if existing_job and existing_job.status in {JobStatus.QUEUED, JobStatus.RUNNING}:
            return existing_job

        job = self.job_service.enqueue(
            db,
            tenant_id=config.tenant_id,
            job_type=JobType.AUDIT_EXPORT_PLACEHOLDER,
            idempotency_key=f"audit_export.placeholder:{config.id}:{utcnow().timestamp()}",
            payload={
                "config_id": config.id,
                "dry_run": dry_run,
                "requested_by_user_id": requested_by.id,
                "ip_address": ip_address,
            },
            max_attempts=(
                1
                if self.job_service.is_inline_dispatch()
                else max(1, get_settings().job_audit_export_max_attempts)
            ),
        )
        config.last_export_job_id = job.id
        config.last_export_status = JobStatus.QUEUED.value
        config.last_error = None
        self.audit_service.create_event(
            db,
            tenant_id=config.tenant_id,
            actor_type=AuditActorType.USER,
            actor_id=requested_by.id,
            event_type=AUDIT_EXPORT_RUN_QUEUED_EVENT,
            resource_type="audit_export_config",
            resource_id=config.id,
            metadata={
                "job_id": job.id,
                "dry_run": dry_run,
                "destination_type": config.destination_type.value,
            },
            ip_address=ip_address,
        )
        return job

    def get_status(self, db: Session, *, tenant_id: str, config_id: str) -> AuditExportStatusResponse:
        config = self.get_config_or_raise(db, tenant_id=tenant_id, config_id=config_id)
        last_job = self._job_for_config(db, config)
        last_result = self.get_job_result(db, job_id=config.last_export_job_id, tenant_id=tenant_id)
        return AuditExportStatusResponse(
            **self._serialize_config(db, config, last_job=last_job).model_dump(),
            pending_events=self.count_pending_events(db, config=config),
            last_result=last_result,
        )

    def count_pending_events(self, db: Session, *, config: AuditExportConfig) -> int:
        return len(self._fetch_exportable_events(db, config=config, limit=None))

    def get_job_result(
        self,
        db: Session,
        *,
        job_id: str | None,
        tenant_id: str,
    ) -> AuditExportRunResult | None:
        if not job_id:
            return None
        job = self.job_service.get_job(db, job_id=job_id, tenant_id=tenant_id)
        if not job:
            return None
        payload = job.payload or {}
        result = payload.get("result")
        if not isinstance(result, dict):
            return None
        return AuditExportRunResult.model_validate(result)

    def handle_audit_export_job(self, db: Session, *, job: Job) -> None:
        payload = job.payload or {}
        config_id = str(payload.get("config_id") or "").strip()
        dry_run = bool(payload.get("dry_run", False))
        requested_by_user_id = str(payload.get("requested_by_user_id") or "").strip() or None
        ip_address = str(payload.get("ip_address") or "").strip() or None
        if not config_id:
            raise JobProcessingError(
                detail="Audit export job payload is invalid.",
                code="audit_export_job_invalid",
                retryable=False,
            )
        config = self.get_config_or_raise(db, tenant_id=job.tenant_id, config_id=config_id)
        if not config.enabled:
            config.last_export_status = JobStatus.FAILED.value
            config.last_error = "Audit export config is disabled."
            raise JobProcessingError(
                detail="Audit export config is disabled.",
                code="audit_export_config_disabled",
                retryable=False,
                persist_state=True,
            )

        config.last_export_job_id = job.id
        config.last_export_status = JobStatus.RUNNING.value
        config.last_error = None
        result = self.run_export(
            db,
            config=config,
            dry_run=dry_run,
            job_id=job.id,
            requested_by_user_id=requested_by_user_id,
            ip_address=ip_address,
        )
        job.payload = {
            **payload,
            "config_id": config.id,
            "result": result.model_dump(mode="json"),
        }

    def handle_audit_export_retry_exhausted(self, db: Session, *, job: Job) -> None:
        config_id = str((job.payload or {}).get("config_id") or "").strip()
        if not config_id:
            return
        config = db.scalar(
            select(AuditExportConfig).where(
                AuditExportConfig.id == config_id,
                AuditExportConfig.tenant_id == job.tenant_id,
            )
        )
        if not config:
            return
        config.last_export_job_id = job.id
        config.last_export_status = JobStatus.RETRY_EXHAUSTED.value
        config.last_error = redact_sensitive_string(job.last_error or "Audit export retries were exhausted.")
        self.audit_service.create_event(
            db,
            tenant_id=job.tenant_id,
            actor_type=AuditActorType.SYSTEM,
            actor_id=None,
            event_type=AUDIT_EXPORT_RUN_RETRY_EXHAUSTED_EVENT,
            resource_type="audit_export_config",
            resource_id=config.id,
            metadata={
                "job_id": job.id,
                "destination_type": config.destination_type.value,
                "detail": config.last_error,
            },
        )

    def run_export(
        self,
        db: Session,
        *,
        config: AuditExportConfig,
        dry_run: bool,
        job_id: str | None,
        requested_by_user_id: str | None,
        ip_address: str | None,
    ) -> AuditExportRunResult:
        exported_events = 0
        batches_processed = 0
        last_exported_at: datetime | None = None
        last_exported_event_id: str | None = None

        while True:
            batch = self._fetch_exportable_events(
                db,
                config=config,
                limit=max(1, config.max_batch_size),
            )
            if not batch:
                break
            batches_processed += 1
            payload_batch = [item.payload for item in batch]
            if not dry_run:
                try:
                    self.dispatcher.send_batch(config, batch=payload_batch)
                except AuditExportDeliveryError as exc:
                    detail = redact_sensitive_string(exc.detail)
                    config.last_export_job_id = job_id
                    config.last_export_status = JobStatus.FAILED.value
                    config.last_error = detail
                    self.audit_service.create_event(
                        db,
                        tenant_id=config.tenant_id,
                        actor_type=AuditActorType.SYSTEM,
                        actor_id=None,
                        event_type=AUDIT_EXPORT_RUN_FAILED_EVENT,
                        resource_type="audit_export_config",
                        resource_id=config.id,
                        metadata={
                            "job_id": job_id,
                            "code": exc.code,
                            "detail": detail,
                            "destination_type": config.destination_type.value,
                        },
                        ip_address=ip_address,
                    )
                    self.metrics.increment("agentgate_audit_export_runs_total", result="failure")
                    raise JobProcessingError(
                        detail=detail,
                        code=exc.code,
                        retryable=exc.retryable,
                        persist_state=True,
                    ) from exc

            exported_events += len(batch)
            last_exported_at = batch[-1].event.created_at
            last_exported_event_id = batch[-1].event.id
            if dry_run:
                continue

            config.last_exported_at = last_exported_at
            config.last_exported_event_id = last_exported_event_id

        result = AuditExportRunResult(
            dry_run=dry_run,
            batches_processed=batches_processed,
            exported_events=exported_events,
            last_exported_at=last_exported_at,
            last_exported_event_id=last_exported_event_id,
            destination_type=config.destination_type,
        )
        config.last_export_job_id = job_id
        config.last_export_status = "dry_run_succeeded" if dry_run else JobStatus.SUCCEEDED.value
        config.last_error = None
        completion_event = (
            AUDIT_EXPORT_RUN_DRY_RUN_COMPLETED_EVENT if dry_run else AUDIT_EXPORT_RUN_SUCCEEDED_EVENT
        )
        self.audit_service.create_event(
            db,
            tenant_id=config.tenant_id,
            actor_type=AuditActorType.SYSTEM,
            actor_id=None,
            event_type=completion_event,
            resource_type="audit_export_config",
            resource_id=config.id,
            metadata={
                "job_id": job_id,
                "dry_run": dry_run,
                "destination_type": config.destination_type.value,
                "exported_events": exported_events,
                "batches_processed": batches_processed,
                "requested_by_user_id": requested_by_user_id,
            },
            ip_address=ip_address,
        )
        self.metrics.increment(
            "agentgate_audit_export_runs_total",
            result="dry_run" if dry_run else "success",
        )
        return result

    def _fetch_exportable_events(
        self,
        db: Session,
        *,
        config: AuditExportConfig,
        limit: int | None,
    ) -> list[ExportableAuditEvent]:
        query = select(AuditEvent).where(AuditEvent.tenant_id == config.tenant_id)
        if config.event_type_filters:
            query = query.where(AuditEvent.event_type.in_(list(config.event_type_filters)))
        if config.last_exported_at:
            query = query.where(
                or_(
                    AuditEvent.created_at > config.last_exported_at,
                    and_(
                        AuditEvent.created_at == config.last_exported_at,
                        AuditEvent.id > (config.last_exported_event_id or ""),
                    ),
                )
            )
        query = query.order_by(AuditEvent.created_at.asc(), AuditEvent.id.asc())
        events = list(db.scalars(query))
        exportable: list[ExportableAuditEvent] = []
        allowed_severities = {
            AuditEventSeverity(item)
            for item in (config.severity_filters or [])
            if str(item).strip()
        }
        for event in events:
            severity = self._classify_severity(event)
            if allowed_severities and severity not in allowed_severities:
                continue
            exportable.append(
                ExportableAuditEvent(
                    event=event,
                    severity=severity,
                    payload=self._serialize_event(event, severity=severity),
                )
            )
            if limit is not None and len(exportable) >= limit:
                break
        return exportable

    def _serialize_event(self, event: AuditEvent, *, severity: AuditEventSeverity) -> dict:
        metadata = self.payload_service.sanitize_payload(event.metadata_json or {})
        payload = {
            "id": event.id,
            "tenant_id": event.tenant_id,
            "actor_type": event.actor_type.value,
            "actor_id": event.actor_id,
            "event_type": event.event_type,
            "severity": severity.value,
            "resource_type": event.resource_type,
            "resource_id": event.resource_id,
            "metadata": metadata,
            "ip_address": event.ip_address,
            "created_at": event.created_at.isoformat(),
        }
        return redact_sensitive_data(payload)

    def _classify_severity(self, event: AuditEvent) -> AuditEventSeverity:
        metadata = event.metadata_json or {}
        explicit = str(metadata.get("severity") or "").strip().lower()
        if explicit in {item.value for item in AuditEventSeverity}:
            return AuditEventSeverity(explicit)
        normalized = event.event_type.lower()
        if "critical" in normalized:
            return AuditEventSeverity.CRITICAL
        if any(token in normalized for token in ("failed", "error", "retry_exhausted", "forbidden", "invalid")):
            return AuditEventSeverity.ERROR
        if any(token in normalized for token in ("blocked", "rejected", "pending_approval", "approval_required")):
            return AuditEventSeverity.WARNING
        return AuditEventSeverity.INFO

    def _serialize_configs(
        self,
        db: Session,
        configs: list[AuditExportConfig],
    ) -> list[AuditExportConfigResponse]:
        if not configs:
            return []
        job_ids = [config.last_export_job_id for config in configs if config.last_export_job_id]
        jobs = []
        if job_ids:
            jobs = list(db.scalars(select(Job).where(Job.id.in_(job_ids))))
        jobs_by_id = {job.id: job for job in jobs}
        return [
            self._serialize_config(db, config, last_job=jobs_by_id.get(config.last_export_job_id or ""))
            for config in configs
        ]

    def _serialize_config(
        self,
        db: Session,
        config: AuditExportConfig,
        *,
        last_job: Job | None = None,
    ) -> AuditExportConfigResponse:
        credential_source, credential_status = self._credential_summary(config)
        return AuditExportConfigResponse(
            id=config.id,
            tenant_id=config.tenant_id,
            name=config.name,
            destination_type=config.destination_type,
            enabled=config.enabled,
            endpoint_url=config.endpoint_url,
            event_type_filters=list(config.event_type_filters or []),
            severity_filters=[AuditEventSeverity(item) for item in (config.severity_filters or [])],
            max_batch_size=config.max_batch_size,
            credential_source=credential_source,
            credential_status=credential_status,
            last_exported_at=config.last_exported_at,
            last_exported_event_id=config.last_exported_event_id,
            last_export_status=config.last_export_status,
            last_error=config.last_error,
            created_at=config.created_at,
            updated_at=config.updated_at,
            last_job=serialize_job_summary(last_job) if last_job else None,
        )

    def _job_for_config(self, db: Session, config: AuditExportConfig) -> Job | None:
        if not config.last_export_job_id:
            return None
        return self.job_service.get_job(db, job_id=config.last_export_job_id, tenant_id=config.tenant_id)

    def _credential_summary(
        self,
        config: AuditExportConfig,
    ) -> tuple[
        str,
        str,
    ]:
        if config.token_env_var:
            try:
                get_secret_resolver().resolve(
                    build_env_secret_reference(config.token_env_var),
                    allow_bare_env=False,
                )
                return "token_env_var", "configured"
            except SecretResolutionError:
                return "token_env_var", "missing"

        if config.secret_ref:
            try:
                get_secret_resolver().resolve(config.secret_ref, allow_bare_env=False)
                return "secret_ref", "configured"
            except SecretResolutionError as exc:
                if exc.code == "invalid_secret_ref":
                    return "secret_ref", "invalid"
                if exc.code == "secret_provider_unconfigured":
                    return "secret_ref", "unsupported"
                return "secret_ref", "missing"

        if config.destination_type in OPTIONAL_AUTH_DESTINATIONS:
            return "none", "not_required"
        return "none", "missing"
