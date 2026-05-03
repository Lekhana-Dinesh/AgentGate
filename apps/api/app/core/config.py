from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from typing import Any

from cryptography.fernet import Fernet
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.networking import (
    is_http_url,
    is_loopback_or_private_url,
    is_production_like_environment,
    normalize_origin,
    uses_https,
)

_ENV_VAR_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SUPPORTED_KEY_PROVIDERS = {
    "env",
    "aws_kms",
    "gcp_kms",
    "azure_key_vault",
    "hashicorp_vault",
}
_WEAK_SECRET_MARKERS = {
    "",
    "changeme",
    "change-me",
    "secret",
    "default",
    "password",
    "agentgate",
}
_DEFAULT_BOOTSTRAP_OWNER_EMAIL = "owner@demo.agentgate.local"
_DEFAULT_BOOTSTRAP_OWNER_PASSWORD = "ChangeThis123!"


def _parse_string_mapping(value: Any) -> dict[str, str]:
    if value in (None, ""):
        return {}
    if isinstance(value, dict):
        source = value
    elif isinstance(value, str):
        try:
            source = json.loads(value)
        except ValueError as exc:
            raise ValueError("Expected a JSON object.") from exc
    else:
        raise ValueError("Expected a JSON object.")

    if not isinstance(source, dict):
        raise ValueError("Expected a JSON object.")

    normalized: dict[str, str] = {}
    for key, item in source.items():
        normalized_key = str(key).strip()
        normalized_value = str(item).strip()
        if not normalized_key or not normalized_value:
            raise ValueError("Mapping entries must use non-empty string keys and values.")
        normalized[normalized_key] = normalized_value
    return normalized


def _env_var_from_secret_reference(value: str) -> str | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    if ":" not in normalized:
        if not _ENV_VAR_PATTERN.match(normalized):
            raise ValueError("Secret references must use env:NAME or a valid bare environment variable name.")
        return normalized
    ref_type, identifier = normalized.split(":", 1)
    normalized_type = ref_type.strip().lower()
    normalized_identifier = identifier.strip()
    if normalized_type == "env":
        if not _ENV_VAR_PATTERN.match(normalized_identifier):
            raise ValueError("env secret references must point to a valid environment variable name.")
        return normalized_identifier
    if normalized_type in {"secret_ref", "vault"}:
        return None
    raise ValueError("Unsupported secret reference type.")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AGENTGATE_", case_sensitive=False)

    project_name: str = "AgentGate"
    environment: str = "development"
    debug: bool = True
    secret_key: str = "change-me-to-a-long-random-development-secret"
    access_token_expire_minutes: int = 60
    database_url: str = "sqlite:///./agentgate.db"
    redis_url: str | None = None
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])
    default_tenant_plan: str = "enterprise-trial"
    auto_create_schema: bool = False
    public_app_url: str = "http://localhost:3000"
    public_api_url: str = "http://localhost:8000"
    allow_insecure_public_urls: bool = False
    key_provider: str = "env"
    payload_encryption_key: str | None = None
    payload_encryption_key_secret_ref: str | None = None
    payload_encryption_active_key_ref: str = "configured-env"
    payload_encryption_key_version: str | None = "1"
    payload_encryption_additional_keys: dict[str, str] = Field(default_factory=dict)
    payload_encryption_additional_key_versions: dict[str, str] = Field(default_factory=dict)
    bootstrap_owner_email: str = _DEFAULT_BOOTSTRAP_OWNER_EMAIL
    bootstrap_owner_password: str = _DEFAULT_BOOTSTRAP_OWNER_PASSWORD
    bootstrap_owner_name: str = "Demo Owner"
    allow_demo_credentials: bool = False
    slack_notifications_enabled: bool = False
    slack_bot_token_env_var: str = "AGENTGATE_SLACK_BOT_TOKEN"
    slack_default_channel: str | None = None
    slack_timeout_seconds: float = 5.0
    audit_export_timeout_seconds: float = 5.0
    allow_private_audit_export_destinations: bool = False
    oidc_http_timeout_seconds: float = 5.0
    oidc_state_ttl_seconds: int = 600
    oidc_exchange_ttl_seconds: int = 180
    job_dispatch_mode: str = "inline"
    job_broker: str = "database"
    job_redis_queue_name: str = "agentgate:jobs"
    job_poll_interval_seconds: float = 2.0
    job_worker_batch_size: int = 10
    job_slack_max_attempts: int = 3
    job_slack_retry_backoff_seconds: float = 30.0
    job_audit_export_max_attempts: int = 3
    job_audit_export_retry_backoff_seconds: float = 30.0
    job_retention_max_attempts: int = 2
    job_retention_retry_backoff_seconds: float = 60.0
    payload_retention_standard_days: int = 30
    payload_retention_short_lived_days: int = 7
    payload_retention_extended_days: int = 90
    rate_limit_enabled: bool | None = None
    rate_limit_login_limit: int = 5
    rate_limit_login_window_seconds: int = 60
    rate_limit_oidc_limit: int = 10
    rate_limit_oidc_window_seconds: int = 60
    rate_limit_gateway_limit: int = 30
    rate_limit_gateway_window_seconds: int = 60
    rate_limit_approval_limit: int = 20
    rate_limit_approval_window_seconds: int = 60
    rate_limit_audit_export_limit: int = 6
    rate_limit_audit_export_window_seconds: int = 300
    rate_limit_retention_limit: int = 4
    rate_limit_retention_window_seconds: int = 300

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, list):
            items = value
        else:
            items = [item.strip() for item in value.split(",") if item.strip()]
        return [normalize_origin(item) for item in items if normalize_origin(item)]

    @field_validator("public_app_url", mode="before")
    @classmethod
    def normalize_public_app_url(cls, value: str) -> str:
        return normalize_origin(value)

    @field_validator("public_api_url", mode="before")
    @classmethod
    def normalize_public_api_url(cls, value: str) -> str:
        return normalize_origin(value)

    @field_validator("key_provider", mode="before")
    @classmethod
    def normalize_key_provider(cls, value: str) -> str:
        normalized = str(value).strip().lower()
        if normalized not in _SUPPORTED_KEY_PROVIDERS:
            raise ValueError(
                "AGENTGATE_KEY_PROVIDER must be one of env, aws_kms, gcp_kms, azure_key_vault, hashicorp_vault."
            )
        return normalized

    @field_validator("payload_encryption_key_secret_ref", mode="before")
    @classmethod
    def normalize_payload_encryption_key_secret_ref(cls, value: str | None) -> str | None:
        normalized = str(value or "").strip()
        return normalized or None

    @field_validator("payload_encryption_active_key_ref", mode="before")
    @classmethod
    def normalize_payload_encryption_active_key_ref(cls, value: str | None) -> str:
        normalized = str(value or "").strip()
        return normalized or "configured-env"

    @field_validator("payload_encryption_key_version", mode="before")
    @classmethod
    def normalize_payload_encryption_key_version(cls, value: str | None) -> str | None:
        normalized = str(value or "").strip()
        return normalized or None

    @field_validator(
        "payload_encryption_additional_keys",
        "payload_encryption_additional_key_versions",
        mode="before",
    )
    @classmethod
    def parse_string_mapping(cls, value: Any) -> dict[str, str]:
        return _parse_string_mapping(value)

    @field_validator("job_dispatch_mode", mode="before")
    @classmethod
    def normalize_job_dispatch_mode(cls, value: str) -> str:
        normalized = str(value).strip().lower()
        if normalized not in {"inline", "worker"}:
            raise ValueError("AGENTGATE_JOB_DISPATCH_MODE must be inline or worker.")
        return normalized

    @field_validator("job_broker", mode="before")
    @classmethod
    def normalize_job_broker(cls, value: str) -> str:
        normalized = str(value).strip().lower()
        if normalized not in {"database", "redis"}:
            raise ValueError("AGENTGATE_JOB_BROKER must be database or redis.")
        return normalized

    @field_validator(
        "rate_limit_login_limit",
        "rate_limit_login_window_seconds",
        "rate_limit_oidc_limit",
        "rate_limit_oidc_window_seconds",
        "rate_limit_gateway_limit",
        "rate_limit_gateway_window_seconds",
        "rate_limit_approval_limit",
        "rate_limit_approval_window_seconds",
        "rate_limit_audit_export_limit",
        "rate_limit_audit_export_window_seconds",
        "rate_limit_retention_limit",
        "rate_limit_retention_window_seconds",
        mode="before",
    )
    @classmethod
    def normalize_positive_ints(cls, value: int | str) -> int:
        normalized = int(value)
        if normalized <= 0:
            raise ValueError("Rate limit values must be positive integers.")
        return normalized

    @model_validator(mode="after")
    def validate_security_defaults(self) -> "Settings":
        production_like = is_production_like_environment(self.environment)
        insecure_secret = self._is_weak_secret(self.secret_key)
        if production_like and insecure_secret:
            raise ValueError(
                "AGENTGATE_SECRET_KEY must be explicitly set to a strong value outside development/test."
            )
        if self.key_provider != "env":
            raise ValueError(
                "AGENTGATE_KEY_PROVIDER currently supports only the env provider in this build."
            )
        if self.job_broker == "redis" and not str(self.redis_url or "").strip():
            raise ValueError("AGENTGATE_REDIS_URL must be configured when AGENTGATE_JOB_BROKER=redis.")

        if production_like:
            if not self.cors_origins:
                raise ValueError("AGENTGATE_CORS_ORIGINS must list explicit origins outside development/test.")
            for origin in self.cors_origins:
                if origin == "*" or "://" not in origin:
                    raise ValueError("AGENTGATE_CORS_ORIGINS must not use wildcard or malformed origins.")
                if is_loopback_or_private_url(origin):
                    raise ValueError(
                        "AGENTGATE_CORS_ORIGINS must not point at localhost or private-network origins outside development/test."
                    )
                if not self.allow_insecure_public_urls and not uses_https(origin):
                    raise ValueError("AGENTGATE_CORS_ORIGINS must use https outside development/test.")

            if not is_http_url(self.public_app_url) or is_loopback_or_private_url(self.public_app_url):
                raise ValueError(
                    "AGENTGATE_PUBLIC_APP_URL must be set to an explicit non-local URL outside development/test."
                )
            if not is_http_url(self.public_api_url) or is_loopback_or_private_url(self.public_api_url):
                raise ValueError(
                    "AGENTGATE_PUBLIC_API_URL must be set to an explicit non-local URL outside development/test."
                )
            if not self.allow_insecure_public_urls and (
                not uses_https(self.public_app_url) or not uses_https(self.public_api_url)
            ):
                raise ValueError(
                    "AGENTGATE_PUBLIC_APP_URL and AGENTGATE_PUBLIC_API_URL must use https outside development/test."
                )
            if self.slack_notifications_enabled and not self.public_app_url:
                raise ValueError(
                    "AGENTGATE_PUBLIC_APP_URL must be configured when Slack approval links are enabled."
                )

        normalized_payload_key = (self.payload_encryption_key or "").strip()
        active_key_value = normalized_payload_key or None
        active_key_ref = self.payload_encryption_active_key_ref
        active_key_secret_ref = str(self.payload_encryption_key_secret_ref or "").strip()
        if active_key_secret_ref:
            env_var = _env_var_from_secret_reference(active_key_secret_ref)
            if env_var is None:
                raise ValueError(
                    "AGENTGATE_PAYLOAD_ENCRYPTION_KEY_SECRET_REF must use an env reference in this build."
                )
            active_key_value = os.getenv(env_var, "").strip() or None
        elif active_key_ref in self.payload_encryption_additional_keys:
            env_var = _env_var_from_secret_reference(self.payload_encryption_additional_keys[active_key_ref])
            if env_var:
                active_key_value = os.getenv(env_var, "").strip() or None
            elif self.environment not in {"development", "test"}:
                raise ValueError(
                    "The active payload encryption key reference must use an env reference in this build."
                )

        if production_like and not active_key_value:
            raise ValueError(
                "A payload encryption key or resolvable active key reference must be configured outside development/test."
            )

        if active_key_value:
            try:
                Fernet(active_key_value.encode("utf-8"))
            except Exception as exc:
                raise ValueError(
                    "The active payload encryption key must be a valid Fernet key."
                ) from exc
        return self

    def _is_weak_secret(self, value: str) -> bool:
        normalized = str(value or "").strip()
        lowered = normalized.lower()
        return (
            len(normalized) < 32
            or lowered.startswith("change-me")
            or lowered in _WEAK_SECRET_MARKERS
            or len(set(normalized)) < 8
        )



@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
