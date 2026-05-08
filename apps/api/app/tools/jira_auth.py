from __future__ import annotations

import base64
from dataclasses import dataclass, field
from typing import Protocol

from app.core.errors import AppError
from app.security.secret_references import (
    SecretResolutionError,
    build_env_secret_reference,
    get_secret_resolver,
)

DEFAULT_JIRA_TOKEN_ENV_VAR = "AGENTGATE_JIRA_TOKEN"
DEFAULT_JIRA_API_TOKEN_ENV_VAR = "AGENTGATE_JIRA_API_TOKEN"
DEFAULT_JIRA_EMAIL_ENV_VAR = "AGENTGATE_JIRA_EMAIL"
JIRA_AUTH_MODE_ENV_TOKEN = "env_token"
JIRA_AUTH_MODE_BASIC_ENV = "basic_env"
JIRA_SUPPORTED_AUTH_MODES = {
    JIRA_AUTH_MODE_ENV_TOKEN,
    JIRA_AUTH_MODE_BASIC_ENV,
}


@dataclass(slots=True)
class JiraAuthContext:
    auth_headers: dict[str, str]
    provider_name: str
    token_env_var: str | None = None
    api_token_env_var: str | None = None
    email_env_var: str | None = None
    token_present: bool = False
    credentials_configured: bool = False
    credential_source: str | None = None
    warnings: list[str] = field(default_factory=list)


class JiraAuthProvider(Protocol):
    provider_name: str

    def get_auth_context(
        self,
        config: dict,
        *,
        require_token: bool = True,
        base_url: str | None = None,
    ) -> JiraAuthContext:
        ...


class EnvironmentTokenJiraAuthProvider:
    provider_name = JIRA_AUTH_MODE_ENV_TOKEN

    def get_auth_context(
        self,
        config: dict,
        *,
        require_token: bool = True,
        base_url: str | None = None,  # noqa: ARG002 - signature compatibility
    ) -> JiraAuthContext:
        token_env_var = str((config or {}).get("token_env_var") or DEFAULT_JIRA_TOKEN_ENV_VAR).strip()
        secret_reference = build_env_secret_reference(token_env_var)
        token = ""
        token_present = False
        try:
            resolved = get_secret_resolver().resolve(secret_reference, allow_bare_env=False)
            token = str(resolved.value or "").strip()
            token_present = bool(token)
        except SecretResolutionError as exc:
            if require_token or exc.code not in {"secret_unavailable"}:
                raise AppError(
                    "Jira connector credentials are not configured for this environment.",
                    status_code=503,
                    code="jira_credentials_missing",
                    extra={"token_env_var": token_env_var},
                ) from exc
        if require_token and not token_present:
            raise AppError(
                "Jira connector credentials are not configured for this environment.",
                status_code=503,
                code="jira_credentials_missing",
                extra={"token_env_var": token_env_var},
            )
        return JiraAuthContext(
            auth_headers=({"Authorization": f"Bearer {token}"} if token_present else {}),
            provider_name=self.provider_name,
            token_env_var=token_env_var,
            token_present=token_present,
            credentials_configured=token_present,
            credential_source="token_env_var",
        )


class BasicEnvironmentJiraAuthProvider:
    provider_name = JIRA_AUTH_MODE_BASIC_ENV

    def get_auth_context(
        self,
        config: dict,
        *,
        require_token: bool = True,
        base_url: str | None = None,  # noqa: ARG002 - signature compatibility
    ) -> JiraAuthContext:
        api_token_env_var = str(
            (config or {}).get("api_token_env_var") or DEFAULT_JIRA_API_TOKEN_ENV_VAR
        ).strip()
        email_env_var = str((config or {}).get("email_env_var") or DEFAULT_JIRA_EMAIL_ENV_VAR).strip()

        token = self._resolve_env_var(
            api_token_env_var,
            require_token=require_token,
            missing_code="jira_credentials_missing",
        )
        email_value = self._resolve_env_var(
            email_env_var,
            require_token=require_token,
            missing_code="jira_credentials_missing",
        )
        token_present = bool(token and email_value)
        if require_token and not token_present:
            raise AppError(
                "Jira connector credentials are not configured for this environment.",
                status_code=503,
                code="jira_credentials_missing",
                extra={
                    "api_token_env_var": api_token_env_var,
                    "email_env_var": email_env_var,
                },
            )

        auth_headers: dict[str, str] = {}
        if token_present:
            encoded = base64.b64encode(f"{email_value}:{token}".encode("utf-8")).decode("ascii")
            auth_headers["Authorization"] = f"Basic {encoded}"
        return JiraAuthContext(
            auth_headers=auth_headers,
            provider_name=self.provider_name,
            api_token_env_var=api_token_env_var,
            email_env_var=email_env_var,
            token_present=token_present,
            credentials_configured=token_present,
            credential_source="basic_env",
        )

    def _resolve_env_var(
        self,
        env_var: str,
        *,
        require_token: bool,
        missing_code: str,
    ) -> str:
        secret_reference = build_env_secret_reference(env_var)
        try:
            resolved = get_secret_resolver().resolve(secret_reference, allow_bare_env=False)
        except SecretResolutionError as exc:
            if require_token or exc.code not in {"secret_unavailable"}:
                raise AppError(
                    "Jira connector credentials are not configured for this environment.",
                    status_code=503,
                    code=missing_code,
                ) from exc
            return ""
        return str(resolved.value or "").strip()


class ConfiguredJiraAuthProvider:
    provider_name = "configured"

    def __init__(
        self,
        *,
        env_provider: JiraAuthProvider | None = None,
        basic_provider: JiraAuthProvider | None = None,
    ) -> None:
        self.env_provider = env_provider or EnvironmentTokenJiraAuthProvider()
        self.basic_provider = basic_provider or BasicEnvironmentJiraAuthProvider()

    def get_auth_context(
        self,
        config: dict,
        *,
        require_token: bool = True,
        base_url: str | None = None,
    ) -> JiraAuthContext:
        auth_mode = str((config or {}).get("auth_mode") or JIRA_AUTH_MODE_ENV_TOKEN).strip().lower()
        if auth_mode == JIRA_AUTH_MODE_ENV_TOKEN:
            return self.env_provider.get_auth_context(
                config,
                require_token=require_token,
                base_url=base_url,
            )
        if auth_mode == JIRA_AUTH_MODE_BASIC_ENV:
            return self.basic_provider.get_auth_context(
                config,
                require_token=require_token,
                base_url=base_url,
            )
        raise AppError(
            "Jira auth_mode is not supported in this build.",
            status_code=422,
            code="jira_auth_mode_unsupported",
        )
