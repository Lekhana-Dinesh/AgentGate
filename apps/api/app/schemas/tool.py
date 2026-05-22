from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import RiskBand, ToolType
from app.schemas.common import ORMModel


class ToolCreate(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    type: ToolType
    description: str = Field(default="", max_length=1000)
    base_url: str | None = Field(default=None, max_length=1000)
    config: dict = Field(default_factory=dict)
    risk_level: RiskBand = RiskBand.MEDIUM
    enabled: bool = True


class ToolUpdate(BaseModel):
    description: str | None = Field(default=None, max_length=1000)
    base_url: str | None = Field(default=None, max_length=1000)
    config: dict | None = None
    risk_level: RiskBand | None = None
    enabled: bool | None = None


class ToolResponse(ORMModel):
    id: str
    tenant_id: str
    name: str
    type: ToolType
    description: str
    base_url: str | None
    config: dict
    risk_level: RiskBand
    enabled: bool
    created_at: datetime
    updated_at: datetime


class ToolHealthResponse(BaseModel):
    tool_id: str
    tool_name: str
    tool_type: ToolType
    status: Literal["ready", "degraded", "unconfigured", "unsupported"]
    adapter: str
    auth_provider: str | None = None
    token_present: bool | None = None
    probe_performed: bool = False
    can_connect: bool | None = None
    details: dict = Field(default_factory=dict)


class ToolSafeSummaryResponse(BaseModel):
    id: str
    name: str
    type: ToolType
    description: str
    enabled: bool
    risk_level: RiskBand
    base_url_host: str | None = None
    auth_mode: str | None = None
    trust_domain: str | None = None
    allowlist_counts: dict[str, int] = Field(default_factory=dict)
    supported_actions: list[str] = Field(default_factory=list)
    health_status: Literal["ready", "degraded", "unconfigured", "unsupported"]
    health_can_connect: bool | None = None
    health_probe_performed: bool = False
    health_checked_at: datetime | None = None
    connector_mode: Literal["demo_safe_mock", "live_connector", "not_applicable"] = "not_applicable"
    live_execution_ready: bool = False
    status_summary: str | None = None
    warning_flags: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class ToolCredentialReference(BaseModel):
    key: str
    label: str
    reference_name: str | None = None
    reference_type: Literal["env", "secret_ref", "vault"] | None = None
    configured: bool | None = None


class ToolProbeObservationResponse(BaseModel):
    status: Literal["ready", "degraded", "unconfigured", "unsupported"]
    checked_at: datetime
    probe_performed: bool
    can_connect: bool | None = None
    error_summary: str | None = None
    source: Literal["manual_probe", "health_check_job"] | None = None


class ToolSafeDetailResponse(ToolSafeSummaryResponse):
    base_url: str | None = None
    documentation_path: str | None = None
    supported_auth_modes: list[str] = Field(default_factory=list)
    credential_references: list[ToolCredentialReference] = Field(default_factory=list)
    validation_messages: list[str] = Field(default_factory=list)
    repository_allowlist: list[str] = Field(default_factory=list)
    internal_repositories: list[str] = Field(default_factory=list)
    internal_owners: list[str] = Field(default_factory=list)
    public_repositories: list[str] = Field(default_factory=list)
    app_id: str | None = None
    installation_id: str | None = None
    project_allowlist: list[str] = Field(default_factory=list)
    issue_type_allowlist: list[str] = Field(default_factory=list)
    external_project_keys: list[str] = Field(default_factory=list)
    transition_allowlist: list[str] = Field(default_factory=list)
    assignee_allowlist: list[str] = Field(default_factory=list)
    transport: str | None = None
    allowed_tool_names: list[str] = Field(default_factory=list)
    blocked_tool_names: list[str] = Field(default_factory=list)
    last_probe: ToolProbeObservationResponse | None = None
    last_successful_probe_at: datetime | None = None
    last_failed_probe_at: datetime | None = None
    last_failed_probe_error_summary: str | None = None


class ToolSafeMetadataCreate(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str = Field(min_length=2, max_length=255)
    type: ToolType
    description: str = Field(default="", max_length=1000)
    base_url: str | None = Field(default=None, max_length=1000)
    risk_level: RiskBand = RiskBand.MEDIUM
    enabled: bool = True
    auth_mode: str | None = Field(default=None, max_length=64)
    trust_domain: Literal["internal", "external", "unknown"] | None = None
    repository_allowlist: list[str] = Field(default_factory=list)
    internal_repositories: list[str] = Field(default_factory=list)
    internal_owners: list[str] = Field(default_factory=list)
    public_repositories: list[str] = Field(default_factory=list)
    app_id: str | None = Field(default=None, max_length=100)
    installation_id: str | None = Field(default=None, max_length=100)
    project_allowlist: list[str] = Field(default_factory=list)
    issue_type_allowlist: list[str] = Field(default_factory=list)
    external_project_keys: list[str] = Field(default_factory=list)
    transition_allowlist: list[str] = Field(default_factory=list)
    assignee_allowlist: list[str] = Field(default_factory=list)
    transport: Literal["http"] | None = None
    allowed_tool_names: list[str] = Field(default_factory=list)
    blocked_tool_names: list[str] = Field(default_factory=list)


class ToolSafeMetadataUpdate(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str | None = Field(default=None, min_length=2, max_length=255)
    description: str | None = Field(default=None, max_length=1000)
    base_url: str | None = Field(default=None, max_length=1000)
    risk_level: RiskBand | None = None
    enabled: bool | None = None
    auth_mode: str | None = Field(default=None, max_length=64)
    trust_domain: Literal["internal", "external", "unknown"] | None = None
    repository_allowlist: list[str] | None = None
    internal_repositories: list[str] | None = None
    internal_owners: list[str] | None = None
    public_repositories: list[str] | None = None
    app_id: str | None = Field(default=None, max_length=100)
    installation_id: str | None = Field(default=None, max_length=100)
    project_allowlist: list[str] | None = None
    issue_type_allowlist: list[str] | None = None
    external_project_keys: list[str] | None = None
    transition_allowlist: list[str] | None = None
    assignee_allowlist: list[str] | None = None
    transport: Literal["http"] | None = None
    allowed_tool_names: list[str] | None = None
    blocked_tool_names: list[str] | None = None
