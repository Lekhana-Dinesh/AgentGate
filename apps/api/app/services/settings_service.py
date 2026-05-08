from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from urllib.parse import urlparse

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.enums import ToolType
from app.core.errors import AppError
from app.models import Agent, AuditExportConfig, ScheduledTask, Tenant, TenantOIDCConfig, Tool, User
from app.models.base import utcnow
from app.schemas.auth import OIDCConfigStatusResponse
from app.schemas.integration import SlackIntegrationHealthResponse
from app.schemas.retention import RetentionStatusResponse, serialize_retention_status
from app.schemas.security import KeyPurposeStatusResponse, KeyStatusResponse
from app.schemas.settings import (
    AuditExportOverviewResponse,
    AuditExportSettingsSummaryResponse,
    GitHubConnectorOverviewResponse,
    GitHubConnectorStatusResponse,
    RateLimiterScopeStatusResponse,
    RateLimiterStatusResponse,
    RetentionPolicyStatusResponse,
    RetentionSettingsOverviewResponse,
    ScheduledTaskOverviewResponse,
    ScheduledTaskSettingsSummaryResponse,
    SettingsLinksResponse,
    SettingsOverviewResponse,
    TenantOIDCSettingsStatusResponse,
    TenantProfileStatusResponse,
)
from app.security.key_management import (
    KEY_PURPOSE_PAYLOAD_PROTECTION,
    KeyManagementError,
    get_key_provider,
)
from app.services.audit_export_service import AuditExportService
from app.services.notification_service import NotificationService
from app.services.oidc_service import OIDCService
from app.services.rate_limit_service import get_rate_limit_settings, get_rate_limiter
from app.services.retention_service import RetentionService
from app.services.tool_health_service import ToolHealthService


class SettingsService:
    def __init__(self) -> None:
        self.audit_export_service = AuditExportService()
        self.notification_service = NotificationService()
        self.oidc_service = OIDCService()
        self.retention_service = RetentionService()
        self.tool_health_service = ToolHealthService()

    def get_overview(self, db: Session, *, tenant_id: str) -> SettingsOverviewResponse:
        tenant = db.scalar(select(Tenant).where(Tenant.id == tenant_id))
        if tenant is None:
            raise AppError("Tenant not found.", status_code=404, code="tenant_not_found")

        return SettingsOverviewResponse(
            tenant=self._tenant_profile(db, tenant=tenant),
            oidc=self._oidc_status(db, tenant=tenant),
            github_connectors=self._github_status(db, tenant_id=tenant.id),
            slack=self._slack_status(),
            audit_exports=self._audit_export_status(db, tenant_id=tenant.id),
            retention=self._retention_status(db, tenant_id=tenant.id),
            scheduled_tasks=self._scheduled_task_status(db, tenant_id=tenant.id),
            keys=self._key_status(),
            rate_limiter=self._rate_limiter_status(),
            links=self._links(),
        )

    def _tenant_profile(self, db: Session, *, tenant: Tenant) -> TenantProfileStatusResponse:
        return TenantProfileStatusResponse(
            id=tenant.id,
            name=tenant.name,
            slug=tenant.slug,
            plan=tenant.plan,
            user_count=self._count_rows(db, User, User.tenant_id == tenant.id),
            active_user_count=self._count_rows(
                db,
                User,
                User.tenant_id == tenant.id,
                User.is_active.is_(True),
            ),
            agent_count=self._count_rows(db, Agent, Agent.tenant_id == tenant.id),
            tool_count=self._count_rows(db, Tool, Tool.tenant_id == tenant.id),
            github_connector_count=self._count_rows(
                db,
                Tool,
                Tool.tenant_id == tenant.id,
                Tool.type == ToolType.GITHUB,
            ),
            audit_export_config_count=self._count_rows(
                db,
                AuditExportConfig,
                AuditExportConfig.tenant_id == tenant.id,
            ),
            scheduled_task_count=self._count_rows(
                db,
                ScheduledTask,
                ScheduledTask.tenant_id == tenant.id,
            ),
            created_at=tenant.created_at,
            updated_at=tenant.updated_at,
        )

    def _oidc_status(self, db: Session, *, tenant: Tenant) -> TenantOIDCSettingsStatusResponse:
        configs = list(
            db.scalars(
                select(TenantOIDCConfig)
                .where(TenantOIDCConfig.tenant_id == tenant.id)
                .order_by(TenantOIDCConfig.created_at.asc())
            )
        )
        enabled_configs = [item for item in configs if item.enabled]
        provider_name = enabled_configs[0].provider_name if enabled_configs else (configs[0].provider_name if configs else None)

        if not configs:
            return TenantOIDCSettingsStatusResponse(
                status="not_configured",
                total_configs=0,
                enabled_configs=0,
                provider_name=None,
                reason=None,
            )

        if not enabled_configs:
            return TenantOIDCSettingsStatusResponse(
                status="disabled",
                total_configs=len(configs),
                enabled_configs=0,
                provider_name=provider_name,
                reason="disabled",
            )

        config_status: OIDCConfigStatusResponse = self.oidc_service.get_config_status(db, tenant_slug=tenant.slug)
        return TenantOIDCSettingsStatusResponse(
            status="ready" if config_status.configured and config_status.enabled else "misconfigured",
            total_configs=len(configs),
            enabled_configs=len(enabled_configs),
            local_auth_enabled=config_status.local_auth_enabled,
            provider_name=config_status.provider_name or provider_name,
            login_url=config_status.login_url,
            reason=config_status.reason,
        )

    def _github_status(self, db: Session, *, tenant_id: str) -> GitHubConnectorOverviewResponse:
        tools = list(
            db.scalars(
                select(Tool)
                .where(Tool.tenant_id == tenant_id, Tool.type == ToolType.GITHUB)
                .order_by(Tool.created_at.desc())
            )
        )

        summaries: list[GitHubConnectorStatusResponse] = []
        counts: Counter[str] = Counter()
        enabled = 0
        for tool in tools:
            if tool.enabled:
                enabled += 1
            health = self.tool_health_service.check(tool=tool, probe=False)
            details = health.details or {}
            warnings = [str(item) for item in (details.get("warnings") or []) if str(item).strip()]
            summary = GitHubConnectorStatusResponse(
                id=tool.id,
                name=tool.name,
                enabled=tool.enabled,
                status=health.status,
                auth_provider=health.auth_provider,
                token_present=health.token_present,
                can_connect=health.can_connect,
                repository_allowlist_count=int(details.get("repository_allowlist_count") or 0),
                warnings=warnings,
                updated_at=tool.updated_at,
            )
            summaries.append(summary)
            counts[summary.status] += 1

        if not tools:
            status = "not_configured"
        elif enabled == 0:
            status = "disabled"
        elif counts["degraded"] or counts["unconfigured"] or counts["unsupported"]:
            status = "degraded"
        else:
            status = "ready"

        return GitHubConnectorOverviewResponse(
            status=status,
            total=len(tools),
            enabled=enabled,
            ready=counts["ready"],
            degraded=counts["degraded"],
            unconfigured=counts["unconfigured"],
            unsupported=counts["unsupported"],
            connectors=summaries,
        )

    def _slack_status(self) -> SlackIntegrationHealthResponse:
        return self.notification_service.slack_health(probe=False)

    def _audit_export_status(self, db: Session, *, tenant_id: str) -> AuditExportOverviewResponse:
        configs = self.audit_export_service.list_configs(db, tenant_id=tenant_id)
        summaries = [
            AuditExportSettingsSummaryResponse(
                id=config.id,
                name=config.name,
                destination_type=config.destination_type,
                enabled=config.enabled,
                endpoint_host=urlparse(config.endpoint_url).netloc or None,
                credential_source=config.credential_source,
                credential_status=config.credential_status,
                last_export_status=config.last_export_status,
                last_error=config.last_error,
                updated_at=config.updated_at,
            )
            for config in configs
        ]
        enabled = sum(1 for item in summaries if item.enabled)
        credential_issue_count = sum(
            1 for item in summaries if item.credential_status not in {"configured", "not_required"}
        )
        failing_count = sum(
            1
            for item in summaries
            if item.last_error or item.last_export_status in {"failed", "retry_exhausted"}
        )

        if not summaries:
            status = "not_configured"
        elif enabled == 0:
            status = "disabled"
        elif credential_issue_count or failing_count:
            status = "degraded"
        else:
            status = "ready"

        return AuditExportOverviewResponse(
            status=status,
            total=len(summaries),
            enabled=enabled,
            credential_issue_count=credential_issue_count,
            failing_count=failing_count,
            configs=summaries,
        )

    def _retention_status(self, db: Session, *, tenant_id: str) -> RetentionSettingsOverviewResponse:
        settings = get_settings()
        summary = self.retention_service.get_status_summary(db, tenant_id=tenant_id)
        serialized_summary: RetentionStatusResponse = serialize_retention_status(summary)
        return RetentionSettingsOverviewResponse(
            status="degraded" if serialized_summary.failed else "ready",
            policy=RetentionPolicyStatusResponse(
                standard_days=settings.payload_retention_standard_days,
                short_lived_days=settings.payload_retention_short_lived_days,
                extended_days=settings.payload_retention_extended_days,
                legal_hold_auto_purge=False,
            ),
            summary=serialized_summary,
        )

    def _scheduled_task_status(self, db: Session, *, tenant_id: str) -> ScheduledTaskOverviewResponse:
        tasks = list(
            db.scalars(
                select(ScheduledTask)
                .where(ScheduledTask.tenant_id == tenant_id)
                .order_by(ScheduledTask.created_at.desc())
            )
        )
        now = self._normalize_datetime(utcnow())
        enabled = sum(1 for item in tasks if item.enabled)
        due = sum(
            1
            for item in tasks
            if item.enabled and self._normalize_datetime(item.next_run_at) <= now
        )
        last_status_counts = Counter((item.last_status or "never_run") for item in tasks)
        task_type_counts = Counter(item.task_type.value for item in tasks)

        if not tasks:
            status = "not_configured"
        elif enabled == 0:
            status = "disabled"
        elif last_status_counts["failed"]:
            status = "degraded"
        else:
            status = "ready"

        return ScheduledTaskOverviewResponse(
            status=status,
            total=len(tasks),
            enabled=enabled,
            due=due,
            last_status_counts=dict(last_status_counts),
            task_type_counts=dict(task_type_counts),
            tasks=[
                ScheduledTaskSettingsSummaryResponse(
                    id=item.id,
                    name=item.name,
                    task_type=item.task_type,
                    enabled=item.enabled,
                    next_run_at=item.next_run_at,
                    last_run_at=item.last_run_at,
                    last_status=item.last_status,
                    last_error=item.last_error,
                    updated_at=item.updated_at,
                )
                for item in tasks
            ],
        )

    def _key_status(self) -> KeyStatusResponse:
        provider = get_key_provider()
        warnings: list[str] = []
        try:
            purpose_status = provider.get_purpose_status(KEY_PURPOSE_PAYLOAD_PROTECTION)
        except KeyManagementError as exc:
            warnings.append(exc.detail)
            purpose_status = KeyPurposeStatusResponse(
                purpose=KEY_PURPOSE_PAYLOAD_PROTECTION,
                provider=provider.provider_name,
                active_key_ref=None,
                active_key_version=None,
                configured_key_refs=[],
                status="unconfigured",
                region=None,
                warnings=[exc.detail],
            )
            return KeyStatusResponse(
                provider=provider.provider_name,
                readiness="unconfigured",
                purposes=[purpose_status],
                warnings=warnings,
            )

        return KeyStatusResponse(
            provider=provider.provider_name,
            readiness=purpose_status.status,
            purposes=[
                KeyPurposeStatusResponse(
                    purpose=purpose_status.purpose,
                    provider=purpose_status.provider,
                    active_key_ref=purpose_status.active_key_ref,
                    active_key_version=purpose_status.active_key_version,
                    configured_key_refs=purpose_status.configured_key_refs,
                    status=purpose_status.status,
                    region=purpose_status.region,
                    warnings=purpose_status.warnings,
                )
            ],
            warnings=warnings + purpose_status.warnings,
        )

    def _rate_limiter_status(self) -> RateLimiterStatusResponse:
        runtime_status = get_rate_limiter().get_status()
        scopes = [
            RateLimiterScopeStatusResponse(
                scope=scope,
                enabled=settings.enabled,
                limit=settings.limit,
                window_seconds=settings.window_seconds,
                fail_closed_on_backend_error=settings.fail_closed_on_backend_error,
            )
            for scope in (
                "login",
                "oidc",
                "gateway",
                "approval",
                "audit_export",
                "retention",
                "jobs_retry",
                "audit_integrity",
            )
            for settings in [get_rate_limit_settings(scope)]
        ]
        return RateLimiterStatusResponse(
            status=str(runtime_status["status"]),
            provider=str(runtime_status["provider"]),
            enabled=bool(runtime_status["enabled"]),
            backend_status=str(runtime_status.get("backend_status") or "") or None,
            warning=str(runtime_status.get("warning") or "") or None,
            scopes=scopes,
        )

    def _links(self) -> SettingsLinksResponse:
        base_url = get_settings().public_api_url.rstrip("/")
        return SettingsLinksResponse(
            readiness_url=f"{base_url}/ready",
            metrics_url=f"{base_url}/metrics",
        )

    def _count_rows(self, db: Session, model, *filters) -> int:
        statement = select(func.count()).select_from(model)
        if filters:
            statement = statement.where(*filters)
        return int(db.scalar(statement) or 0)

    def _normalize_datetime(self, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
