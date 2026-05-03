from __future__ import annotations

import logging
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.enums import AuditActorType, JobStatus, JobType
from app.core.metrics import get_metrics_registry
from app.core.redaction import redact_sensitive_data
from app.models import Agent, ApprovalRequest, AuditEvent, Job, ToolCall
from app.notifications.slack_notifier import SlackApprovalSummary, SlackNotifier
from app.security.secret_references import build_env_secret_reference, get_secret_resolver
from app.schemas.integration import ApprovalNotificationStatus, SlackIntegrationHealthResponse
from app.schemas.job import serialize_job_summary
from app.services.audit_service import AuditService
from app.services.job_service import JobProcessingError, JobService

logger = logging.getLogger(__name__)
SLACK_QUEUED_EVENT = "notification.slack.approval_request.queued"
SLACK_SENT_EVENT = "notification.slack.approval_request.sent"
SLACK_FAILED_EVENT = "notification.slack.approval_request.failed"
SLACK_RETRY_EXHAUSTED_EVENT = "notification.slack.approval_request.retry_exhausted"


class NotificationService:
    def __init__(self, slack_notifier: SlackNotifier | None = None) -> None:
        self.audit_service = AuditService()
        self.job_service = JobService()
        self.slack_notifier = slack_notifier or SlackNotifier()
        self.metrics = get_metrics_registry()

    def job_idempotency_key(self, approval_id: str) -> str:
        return f"approval_notification.slack:{approval_id}"

    def notify_approval_request_created(
        self,
        db: Session,
        *,
        approval: ApprovalRequest,
        tool_call: ToolCall,
        agent: Agent,
        request_id: str | None = None,
        ip_address: str | None = None,
    ) -> None:
        try:
            settings = get_settings()
            if not settings.slack_notifications_enabled:
                return

            job = self.job_service.enqueue(
                db,
                tenant_id=approval.tenant_id,
                job_type=JobType.APPROVAL_NOTIFICATION_SLACK,
                idempotency_key=self.job_idempotency_key(approval.id),
                payload={
                    "approval_id": approval.id,
                    "tool_call_id": tool_call.id,
                    "agent_id": agent.id,
                    "request_id": request_id,
                    "ip_address": ip_address,
                },
                max_attempts=(
                    1
                    if self.job_service.is_inline_dispatch()
                    else max(1, settings.job_slack_max_attempts)
                ),
            )
            self.audit_service.create_event(
                db,
                tenant_id=approval.tenant_id,
                actor_type=AuditActorType.SYSTEM,
                actor_id=None,
                event_type=SLACK_QUEUED_EVENT,
                resource_type="approval_request",
                resource_id=approval.id,
                metadata={
                    "provider": "slack",
                    "approval_id": approval.id,
                    "tool_call_id": tool_call.id,
                    "agent_id": agent.id,
                    "request_id": request_id,
                    "job_id": job.id,
                },
                ip_address=ip_address,
            )
            db.commit()
            self.job_service.dispatch_after_commit(db, job_id=job.id, raise_on_error=False)
        except Exception:
            db.rollback()
            logger.warning(
                "slack_notification_service_unavailable",
                extra={
                    "event_type": "slack_notification_service_unavailable",
                    "status_code": None,
                    "request_id": request_id,
                },
                exc_info=True,
            )

    def handle_slack_approval_notification_job(self, db: Session, *, job: Job) -> None:
        approval_id = str(job.payload.get("approval_id") or "").strip()
        tool_call_id = str(job.payload.get("tool_call_id") or "").strip()
        agent_id = str(job.payload.get("agent_id") or "").strip()
        request_id = str(job.payload.get("request_id") or "").strip() or None
        ip_address = str(job.payload.get("ip_address") or "").strip() or None
        if not approval_id or not tool_call_id or not agent_id:
            raise JobProcessingError(
                detail="Slack notification job payload is invalid.",
                code="slack_notification_job_invalid",
                retryable=False,
            )

        approval = db.scalar(
            select(ApprovalRequest).where(
                ApprovalRequest.id == approval_id,
                ApprovalRequest.tenant_id == job.tenant_id,
            )
        )
        tool_call = db.scalar(
            select(ToolCall).where(
                ToolCall.id == tool_call_id,
                ToolCall.tenant_id == job.tenant_id,
            )
        )
        agent = db.scalar(
            select(Agent).where(
                Agent.id == agent_id,
                Agent.tenant_id == job.tenant_id,
            )
        )
        if not approval or not tool_call or not agent:
            raise JobProcessingError(
                detail="Slack notification target was not found in the tenant.",
                code="slack_notification_target_not_found",
                retryable=False,
            )

        settings = get_settings()
        summary = self._build_slack_summary(
            approval=approval,
            tool_call=tool_call,
            agent=agent,
            request_id=request_id,
        )
        result = self.slack_notifier.send_approval_notification(
            summary,
            token_env_var=settings.slack_bot_token_env_var,
            default_channel=settings.slack_default_channel,
            timeout_seconds=settings.slack_timeout_seconds,
        )
        metadata = {
            "provider": "slack",
            "approval_id": approval.id,
            "tool_call_id": tool_call.id,
            "agent_id": agent.id,
            "job_id": job.id,
            "request_id": request_id,
            "status": result.status,
            "code": result.code,
            "channel": result.metadata.get("channel") or settings.slack_default_channel,
            "detail": result.detail,
            "trace_id": tool_call.trace_id,
        }
        if result.success:
            self.audit_service.create_event(
                db,
                tenant_id=approval.tenant_id,
                actor_type=AuditActorType.SYSTEM,
                actor_id=None,
                event_type=SLACK_SENT_EVENT,
                resource_type="approval_request",
                resource_id=approval.id,
                metadata=redact_sensitive_data(metadata | {"message_ts": result.metadata.get("ts")}),
                ip_address=ip_address,
            )
            self.metrics.increment("agentgate_slack_notifications_total", result="success")
            return

        logger.warning(
            "slack_notification_failed",
            extra={
                "event_type": "slack_notification_failed",
                "status_code": None,
                "request_id": request_id,
            },
        )
        self.audit_service.create_event(
            db,
            tenant_id=approval.tenant_id,
            actor_type=AuditActorType.SYSTEM,
            actor_id=None,
            event_type=SLACK_FAILED_EVENT,
            resource_type="approval_request",
            resource_id=approval.id,
            metadata=redact_sensitive_data(metadata),
            ip_address=ip_address,
        )
        self.metrics.increment("agentgate_slack_notifications_total", result="failure")
        raise JobProcessingError(
            detail=result.detail,
            code=result.code,
            retryable=self._is_retryable_failure(result.code),
            persist_state=True,
        )

    def handle_slack_retry_exhausted(self, db: Session, *, job: Job) -> None:
        approval_id = str(job.payload.get("approval_id") or "").strip()
        ip_address = str(job.payload.get("ip_address") or "").strip() or None
        if not approval_id:
            return
        self.audit_service.create_event(
            db,
            tenant_id=job.tenant_id,
            actor_type=AuditActorType.SYSTEM,
            actor_id=None,
            event_type=SLACK_RETRY_EXHAUSTED_EVENT,
            resource_type="approval_request",
            resource_id=approval_id,
            metadata={
                "provider": "slack",
                "job_id": job.id,
                "code": "slack_retry_exhausted",
                "detail": job.last_error,
            },
            ip_address=ip_address,
        )
        self.metrics.increment("agentgate_slack_notifications_total", result="retry_exhausted")

    def get_approval_notification_status(
        self,
        db: Session,
        *,
        tenant_id: str,
        approval_id: str,
    ) -> ApprovalNotificationStatus:
        settings = get_settings()
        job = db.scalar(
            select(Job).where(
                Job.tenant_id == tenant_id,
                Job.idempotency_key == self.job_idempotency_key(approval_id),
            )
        )
        events = list(
            db.scalars(
                select(AuditEvent)
                .where(
                    AuditEvent.tenant_id == tenant_id,
                    AuditEvent.resource_type == "approval_request",
                    AuditEvent.resource_id == approval_id,
                    AuditEvent.event_type.in_(
                        [
                            SLACK_QUEUED_EVENT,
                            SLACK_SENT_EVENT,
                            SLACK_FAILED_EVENT,
                            SLACK_RETRY_EXHAUSTED_EVENT,
                        ]
                    ),
                )
                .order_by(AuditEvent.created_at.desc())
            )
        )
        return self._status_from_job_and_event(
            job,
            event=self._select_event_for_job(job, events),
            settings=settings,
        )

    def map_notification_statuses(
        self,
        db: Session,
        *,
        tenant_id: str,
        approval_ids: Iterable[str],
    ) -> dict[str, ApprovalNotificationStatus]:
        settings = get_settings()
        ids = list(approval_ids)
        if not ids:
            return {}

        jobs = list(
            db.scalars(
                select(Job).where(
                    Job.tenant_id == tenant_id,
                    Job.idempotency_key.in_([self.job_idempotency_key(item) for item in ids]),
                )
            )
        )
        jobs_by_key = {job.idempotency_key: job for job in jobs}
        events = list(
            db.scalars(
                select(AuditEvent)
                .where(
                    AuditEvent.tenant_id == tenant_id,
                    AuditEvent.resource_type == "approval_request",
                    AuditEvent.resource_id.in_(ids),
                    AuditEvent.event_type.in_(
                        [
                            SLACK_QUEUED_EVENT,
                            SLACK_SENT_EVENT,
                            SLACK_FAILED_EVENT,
                            SLACK_RETRY_EXHAUSTED_EVENT,
                        ]
                    ),
                )
                .order_by(AuditEvent.created_at.desc())
            )
        )
        by_resource: dict[str, list[AuditEvent]] = {}
        for event in events:
            if event.resource_id:
                by_resource.setdefault(event.resource_id, []).append(event)

        return {
            approval_id: self._status_from_job_and_event(
                jobs_by_key.get(self.job_idempotency_key(approval_id)),
                event=self._select_event_for_job(
                    jobs_by_key.get(self.job_idempotency_key(approval_id)),
                    by_resource.get(approval_id, []),
                ),
                settings=settings,
            )
            for approval_id in ids
        }

    def slack_health(self, *, probe: bool = False) -> SlackIntegrationHealthResponse:
        settings = get_settings()
        result = self.slack_notifier.health_check(
            enabled=settings.slack_notifications_enabled,
            token_env_var=settings.slack_bot_token_env_var,
            default_channel=settings.slack_default_channel,
            timeout_seconds=settings.slack_timeout_seconds,
            probe=probe,
        )
        return SlackIntegrationHealthResponse(
            enabled=result.enabled,
            configured=result.configured,
            status=result.status,
            token_env_var=result.token_env_var,
            default_channel=result.default_channel,
            probe_performed=result.probe_performed,
            can_connect=result.can_connect,
            details=redact_sensitive_data(result.details),
        )

    def _build_slack_summary(
        self,
        *,
        approval: ApprovalRequest,
        tool_call: ToolCall,
        agent: Agent,
        request_id: str | None,
    ) -> SlackApprovalSummary:
        settings = get_settings()
        response_payload = tool_call.response_payload or {}
        policies = (response_payload.get("policies") or {}).get("matched_policies") or []
        risk = response_payload.get("risk") or {}
        request_payload = tool_call.request_payload or {}
        dashboard_url = settings.public_app_url if settings.public_app_url else None
        return SlackApprovalSummary(
            approval_id=approval.id,
            tenant_id=approval.tenant_id,
            agent_name=agent.name,
            agent_id=agent.id,
            tool_name=tool_call.tool_name,
            action_name=tool_call.action_name,
            risk_score=float(tool_call.risk_score),
            risk_band=str(risk.get("band") or "unknown"),
            policy_names=[str(item.get("name")) for item in policies if item.get("name")],
            original_intent=str(request_payload.get("original_intent") or ""),
            sanitized_arguments=redact_sensitive_data(request_payload.get("arguments") or {}),
            dashboard_url=dashboard_url,
            trace_id=tool_call.trace_id,
            request_id=request_id,
        )

    def _status_from_job_and_event(
        self,
        job: Job | None,
        *,
        event: AuditEvent | None,
        settings,
    ) -> ApprovalNotificationStatus:
        if job is None:
            if not settings.slack_notifications_enabled:
                return ApprovalNotificationStatus(provider="slack", status="disabled")
            try:
                get_secret_resolver().resolve(
                    build_env_secret_reference(settings.slack_bot_token_env_var),
                    allow_bare_env=False,
                )
                token_present = True
            except Exception:
                token_present = False
            if not token_present:
                return ApprovalNotificationStatus(
                    provider="slack",
                    status="unconfigured",
                    error_code="slack_token_missing",
                    message="Slack bot token is not configured for this environment.",
                )
            if not settings.slack_default_channel:
                return ApprovalNotificationStatus(
                    provider="slack",
                    status="unconfigured",
                    error_code="slack_channel_missing",
                    message="Slack default channel is not configured.",
                )
            return ApprovalNotificationStatus(provider="slack", status="not_attempted")

        metadata = redact_sensitive_data((event.metadata_json or {}) if event else {})
        base_kwargs = {
            "provider": "slack",
            "job_id": job.id,
            "job": serialize_job_summary(job),
            "attempts": job.attempts,
            "max_attempts": job.max_attempts,
        }
        if job.status == JobStatus.QUEUED:
            return ApprovalNotificationStatus(
                **base_kwargs,
                status="queued",
                event_type=event.event_type if event else None,
                message="Slack notification is queued for delivery.",
                created_at=job.updated_at,
            )
        if job.status == JobStatus.RUNNING:
            return ApprovalNotificationStatus(
                **base_kwargs,
                status="running",
                event_type=event.event_type if event else None,
                message="Slack notification is being delivered.",
                created_at=job.updated_at,
            )
        if job.status == JobStatus.SUCCEEDED:
            return ApprovalNotificationStatus(
                **base_kwargs,
                status="sent",
                event_type=event.event_type if event else SLACK_SENT_EVENT,
                message=str(metadata.get("detail") or "Slack notification sent successfully."),
                request_id=str(metadata.get("request_id") or "") or None,
                channel=str(metadata.get("channel") or "") or None,
                created_at=(event.created_at if event else job.completed_at),
            )
        if job.status == JobStatus.RETRY_EXHAUSTED:
            return ApprovalNotificationStatus(
                **base_kwargs,
                status="retry_exhausted",
                event_type=event.event_type if event else SLACK_RETRY_EXHAUSTED_EVENT,
                message=str(metadata.get("detail") or job.last_error or "Slack retries were exhausted."),
                error_code=str(metadata.get("code") or "slack_retry_exhausted"),
                request_id=str(metadata.get("request_id") or "") or None,
                channel=str(metadata.get("channel") or "") or None,
                created_at=(event.created_at if event else job.completed_at),
            )
        if job.status == JobStatus.CANCELLED:
            return ApprovalNotificationStatus(
                **base_kwargs,
                status="cancelled",
                event_type=event.event_type if event else None,
                message="Slack notification delivery was cancelled.",
                created_at=job.completed_at,
            )
        return ApprovalNotificationStatus(
            **base_kwargs,
            status="failed",
            event_type=event.event_type if event else SLACK_FAILED_EVENT,
            message=str(metadata.get("detail") or job.last_error or "Slack notification failed."),
            error_code=str(metadata.get("code") or "") or None,
            request_id=str(metadata.get("request_id") or "") or None,
            channel=str(metadata.get("channel") or "") or None,
            created_at=(event.created_at if event else job.completed_at),
        )

    def _is_retryable_failure(self, code: str) -> bool:
        return code in {"slack_rate_limited", "slack_upstream_unavailable"}

    def _select_event_for_job(self, job: Job | None, events: list[AuditEvent]) -> AuditEvent | None:
        if not events:
            return None
        if job is None:
            return events[0]

        preferred_by_status = {
            JobStatus.QUEUED: [SLACK_QUEUED_EVENT],
            JobStatus.RUNNING: [SLACK_QUEUED_EVENT],
            JobStatus.SUCCEEDED: [SLACK_SENT_EVENT],
            JobStatus.FAILED: [SLACK_FAILED_EVENT],
            JobStatus.RETRY_EXHAUSTED: [SLACK_RETRY_EXHAUSTED_EVENT, SLACK_FAILED_EVENT],
            JobStatus.CANCELLED: [SLACK_QUEUED_EVENT],
        }
        for event_type in preferred_by_status.get(job.status, []):
            for event in events:
                if event.event_type == event_type:
                    return event
        return events[0]
