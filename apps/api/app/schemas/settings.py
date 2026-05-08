from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.core.enums import AuditExportDestinationType, ScheduledTaskType
from app.schemas.integration import SlackIntegrationHealthResponse
from app.schemas.retention import RetentionStatusResponse
from app.schemas.security import KeyStatusResponse


class TenantProfileStatusResponse(BaseModel):
    id: str
    name: str
    slug: str
    plan: str
    user_count: int
    active_user_count: int
    agent_count: int
    tool_count: int
    github_connector_count: int
    audit_export_config_count: int
    scheduled_task_count: int
    created_at: datetime
    updated_at: datetime


class TenantOIDCSettingsStatusResponse(BaseModel):
    status: Literal["not_configured", "disabled", "ready", "misconfigured"]
    total_configs: int
    enabled_configs: int
    local_auth_enabled: bool = True
    provider_name: str | None = None
    login_url: str | None = None
    reason: str | None = None


class GitHubConnectorStatusResponse(BaseModel):
    id: str
    name: str
    enabled: bool
    status: Literal["ready", "degraded", "unconfigured", "unsupported"]
    auth_provider: str | None = None
    token_present: bool | None = None
    can_connect: bool | None = None
    repository_allowlist_count: int = 0
    warnings: list[str] = Field(default_factory=list)
    updated_at: datetime


class GitHubConnectorOverviewResponse(BaseModel):
    status: Literal["not_configured", "disabled", "ready", "degraded"]
    total: int
    enabled: int
    ready: int
    degraded: int
    unconfigured: int
    unsupported: int
    connectors: list[GitHubConnectorStatusResponse] = Field(default_factory=list)


class AuditExportSettingsSummaryResponse(BaseModel):
    id: str
    name: str
    destination_type: AuditExportDestinationType
    enabled: bool
    endpoint_host: str | None = None
    credential_source: Literal["none", "token_env_var", "secret_ref"]
    credential_status: Literal["not_required", "configured", "missing", "unsupported", "invalid"]
    last_export_status: str | None = None
    last_error: str | None = None
    updated_at: datetime


class AuditExportOverviewResponse(BaseModel):
    status: Literal["not_configured", "disabled", "ready", "degraded"]
    total: int
    enabled: int
    credential_issue_count: int
    failing_count: int
    configs: list[AuditExportSettingsSummaryResponse] = Field(default_factory=list)


class RetentionPolicyStatusResponse(BaseModel):
    standard_days: int
    short_lived_days: int
    extended_days: int
    legal_hold_auto_purge: bool = False


class RetentionSettingsOverviewResponse(BaseModel):
    status: Literal["ready", "degraded"]
    policy: RetentionPolicyStatusResponse
    summary: RetentionStatusResponse


class ScheduledTaskSettingsSummaryResponse(BaseModel):
    id: str
    name: str
    task_type: ScheduledTaskType
    enabled: bool
    next_run_at: datetime
    last_run_at: datetime | None = None
    last_status: str | None = None
    last_error: str | None = None
    updated_at: datetime


class ScheduledTaskOverviewResponse(BaseModel):
    status: Literal["not_configured", "disabled", "ready", "degraded"]
    total: int
    enabled: int
    due: int
    last_status_counts: dict[str, int] = Field(default_factory=dict)
    task_type_counts: dict[str, int] = Field(default_factory=dict)
    tasks: list[ScheduledTaskSettingsSummaryResponse] = Field(default_factory=list)


class RateLimiterScopeStatusResponse(BaseModel):
    scope: str
    enabled: bool
    limit: int
    window_seconds: int
    fail_closed_on_backend_error: bool


class RateLimiterStatusResponse(BaseModel):
    status: Literal["disabled", "ok", "warning", "unavailable"]
    provider: str
    enabled: bool
    backend_status: str | None = None
    warning: str | None = None
    scopes: list[RateLimiterScopeStatusResponse] = Field(default_factory=list)


class SettingsLinksResponse(BaseModel):
    readiness_url: str
    metrics_url: str


class SettingsOverviewResponse(BaseModel):
    tenant: TenantProfileStatusResponse
    oidc: TenantOIDCSettingsStatusResponse
    github_connectors: GitHubConnectorOverviewResponse
    slack: SlackIntegrationHealthResponse
    audit_exports: AuditExportOverviewResponse
    retention: RetentionSettingsOverviewResponse
    scheduled_tasks: ScheduledTaskOverviewResponse
    keys: KeyStatusResponse
    rate_limiter: RateLimiterStatusResponse
    links: SettingsLinksResponse
