from __future__ import annotations

import re
from datetime import datetime
from typing import Literal
from urllib.parse import urlparse

from app.core.config import get_settings
from app.core.networking import is_loopback_or_private_url, is_production_like_environment
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.enums import AuditExportDestinationType, AuditEventSeverity
from app.schemas.common import ORMModel
from app.schemas.job import JobResponse, JobSummary
from app.security.secret_references import SecretResolutionError, get_secret_resolver

_ENV_VAR_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _normalize_endpoint_url(value: str) -> str:
    normalized = str(value or "").strip()
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("endpoint_url must be a valid http or https URL.")
    if parsed.username or parsed.password:
        raise ValueError("endpoint_url must not embed credentials.")
    if parsed.query or parsed.fragment:
        raise ValueError("endpoint_url must not include query parameters or fragments.")
    settings = get_settings()
    if (
        is_production_like_environment(settings.environment)
        and not settings.allow_private_audit_export_destinations
        and is_loopback_or_private_url(normalized)
    ):
        raise ValueError(
            "endpoint_url must not target localhost or private-network destinations outside development/test."
        )
    return normalized.rstrip("/")


def _normalize_secret_ref(value: str | None) -> str | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    try:
        get_secret_resolver().parse(normalized, allow_bare_env=False)
    except SecretResolutionError as exc:
        raise ValueError("secret_ref must use a valid env, secret_ref, or vault reference.") from exc
    return normalized


def _normalize_event_filters(values: list[str] | None) -> list[str]:
    if not values:
        return []
    normalized: list[str] = []
    for value in values:
        item = str(value or "").strip()
        if item:
            normalized.append(item)
    return list(dict.fromkeys(normalized))


class AuditExportBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=2, max_length=255)
    destination_type: AuditExportDestinationType
    enabled: bool = False
    endpoint_url: str = Field(min_length=1, max_length=1000)
    secret_ref: str | None = Field(default=None, max_length=255)
    token_env_var: str | None = Field(default=None, max_length=255)
    event_type_filters: list[str] = Field(default_factory=list)
    severity_filters: list[AuditEventSeverity] = Field(default_factory=list)
    max_batch_size: int = Field(default=100, ge=1, le=500)

    @field_validator("endpoint_url", mode="before")
    @classmethod
    def normalize_endpoint_url(cls, value: str) -> str:
        return _normalize_endpoint_url(value)

    @field_validator("secret_ref", mode="before")
    @classmethod
    def normalize_secret_ref(cls, value: str | None) -> str | None:
        return _normalize_secret_ref(value)

    @field_validator("token_env_var", mode="before")
    @classmethod
    def normalize_token_env_var(cls, value: str | None) -> str | None:
        normalized = str(value or "").strip()
        if not normalized:
            return None
        if not _ENV_VAR_PATTERN.match(normalized):
            raise ValueError("token_env_var must be a valid environment variable name.")
        return normalized

    @field_validator("event_type_filters", mode="before")
    @classmethod
    def normalize_event_type_filters(cls, value) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("event_type_filters must be a list of strings.")
        return _normalize_event_filters(value)

    @model_validator(mode="after")
    def validate_auth_requirements(self) -> "AuditExportBase":
        if self.secret_ref and self.token_env_var:
            raise ValueError("Configure either secret_ref or token_env_var, not both.")
        if self.destination_type in {
            AuditExportDestinationType.SPLUNK_HEC,
            AuditExportDestinationType.DATADOG,
        } and not (self.secret_ref or self.token_env_var):
            raise ValueError("This destination type requires token_env_var or secret_ref.")
        return self


class AuditExportCreate(AuditExportBase):
    pass


class AuditExportUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=2, max_length=255)
    destination_type: AuditExportDestinationType | None = None
    enabled: bool | None = None
    endpoint_url: str | None = Field(default=None, min_length=1, max_length=1000)
    secret_ref: str | None = Field(default=None, max_length=255)
    token_env_var: str | None = Field(default=None, max_length=255)
    event_type_filters: list[str] | None = None
    severity_filters: list[AuditEventSeverity] | None = None
    max_batch_size: int | None = Field(default=None, ge=1, le=500)

    @field_validator("endpoint_url", mode="before")
    @classmethod
    def normalize_endpoint_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _normalize_endpoint_url(value)

    @field_validator("secret_ref", mode="before")
    @classmethod
    def normalize_secret_ref(cls, value: str | None) -> str | None:
        return _normalize_secret_ref(value)

    @field_validator("token_env_var", mode="before")
    @classmethod
    def normalize_token_env_var(cls, value: str | None) -> str | None:
        normalized = str(value or "").strip()
        if not normalized:
            return None
        if not _ENV_VAR_PATTERN.match(normalized):
            raise ValueError("token_env_var must be a valid environment variable name.")
        return normalized

    @field_validator("event_type_filters", mode="before")
    @classmethod
    def normalize_event_type_filters(cls, value) -> list[str] | None:
        if value is None:
            return None
        if not isinstance(value, list):
            raise ValueError("event_type_filters must be a list of strings.")
        return _normalize_event_filters(value)


class AuditExportRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dry_run: bool = False


class AuditExportRunResult(BaseModel):
    dry_run: bool
    batches_processed: int
    exported_events: int
    last_exported_at: datetime | None = None
    last_exported_event_id: str | None = None
    destination_type: AuditExportDestinationType


class AuditExportConfigResponse(ORMModel):
    id: str
    tenant_id: str
    name: str
    destination_type: AuditExportDestinationType
    enabled: bool
    endpoint_url: str
    event_type_filters: list[str]
    severity_filters: list[AuditEventSeverity]
    max_batch_size: int
    credential_source: Literal["none", "token_env_var", "secret_ref"]
    credential_status: Literal["not_required", "configured", "missing", "unsupported", "invalid"]
    last_exported_at: datetime | None = None
    last_exported_event_id: str | None = None
    last_export_status: str | None = None
    last_error: str | None = None
    created_at: datetime
    updated_at: datetime
    last_job: JobSummary | None = None


class AuditExportStatusResponse(AuditExportConfigResponse):
    pending_events: int = 0
    last_result: AuditExportRunResult | None = None


class AuditExportRunResponse(BaseModel):
    dry_run: bool
    dispatch_mode: Literal["inline", "worker"]
    job: JobResponse
    result: AuditExportRunResult | None = None
