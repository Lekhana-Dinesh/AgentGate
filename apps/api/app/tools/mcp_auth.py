from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from app.core.errors import AppError
from app.security.secret_references import (
    SecretResolutionError,
    build_env_secret_reference,
    get_secret_resolver,
)

DEFAULT_MCP_TOKEN_ENV_VAR = "AGENTGATE_MCP_TOKEN"
DEFAULT_MCP_API_KEY_ENV_VAR = "AGENTGATE_MCP_API_KEY"
DEFAULT_MCP_API_KEY_HEADER = "X-API-Key"
MCP_AUTH_MODE_NONE = "none"
MCP_AUTH_MODE_BEARER_ENV = "bearer_env"
MCP_AUTH_MODE_API_KEY_ENV = "api_key_env"
MCP_SUPPORTED_AUTH_MODES = {
    MCP_AUTH_MODE_NONE,
    MCP_AUTH_MODE_BEARER_ENV,
    MCP_AUTH_MODE_API_KEY_ENV,
}


@dataclass(slots=True)
class MCPAuthContext:
    auth_headers: dict[str, str]
    provider_name: str
    token_env_var: str | None = None
    api_key_env_var: str | None = None
    token_present: bool = False
    credentials_configured: bool = False
    credential_source: str | None = None
    warnings: list[str] = field(default_factory=list)


class MCPAuthProvider(Protocol):
    provider_name: str

    def get_auth_context(
        self,
        config: dict,
        *,
        require_token: bool = True,
        base_url: str | None = None,
    ) -> MCPAuthContext:
        ...


class NoAuthMCPAuthProvider:
    provider_name = MCP_AUTH_MODE_NONE

    def get_auth_context(
        self,
        config: dict,
        *,
        require_token: bool = True,  # noqa: ARG002 - signature compatibility
        base_url: str | None = None,  # noqa: ARG002 - signature compatibility
    ) -> MCPAuthContext:
        return MCPAuthContext(
            auth_headers={},
            provider_name=self.provider_name,
            token_present=False,
            credentials_configured=True,
            credential_source="none",
        )


class BearerEnvironmentMCPAuthProvider:
    provider_name = MCP_AUTH_MODE_BEARER_ENV

    def get_auth_context(
        self,
        config: dict,
        *,
        require_token: bool = True,
        base_url: str | None = None,  # noqa: ARG002 - signature compatibility
    ) -> MCPAuthContext:
        token_env_var = str((config or {}).get("token_env_var") or DEFAULT_MCP_TOKEN_ENV_VAR).strip()
        token = self._resolve_env_secret(token_env_var, require_token=require_token)
        token_present = bool(token)
        if require_token and not token_present:
            raise AppError(
                "MCP connector credentials are not configured for this environment.",
                status_code=503,
                code="mcp_credentials_missing",
                extra={"token_env_var": token_env_var},
            )
        return MCPAuthContext(
            auth_headers=({"Authorization": f"Bearer {token}"} if token_present else {}),
            provider_name=self.provider_name,
            token_env_var=token_env_var,
            token_present=token_present,
            credentials_configured=token_present,
            credential_source="token_env_var",
        )

    def _resolve_env_secret(self, env_var: str, *, require_token: bool) -> str:
        secret_reference = build_env_secret_reference(env_var)
        try:
            resolved = get_secret_resolver().resolve(secret_reference, allow_bare_env=False)
        except SecretResolutionError as exc:
            if require_token or exc.code not in {"secret_unavailable"}:
                raise AppError(
                    "MCP connector credentials are not configured for this environment.",
                    status_code=503,
                    code="mcp_credentials_missing",
                ) from exc
            return ""
        return str(resolved.value or "").strip()


class APIKeyEnvironmentMCPAuthProvider:
    provider_name = MCP_AUTH_MODE_API_KEY_ENV

    def get_auth_context(
        self,
        config: dict,
        *,
        require_token: bool = True,
        base_url: str | None = None,  # noqa: ARG002 - signature compatibility
    ) -> MCPAuthContext:
        api_key_env_var = str(
            (config or {}).get("api_key_env_var") or DEFAULT_MCP_API_KEY_ENV_VAR
        ).strip()
        api_key = self._resolve_env_secret(api_key_env_var, require_token=require_token)
        token_present = bool(api_key)
        if require_token and not token_present:
            raise AppError(
                "MCP connector credentials are not configured for this environment.",
                status_code=503,
                code="mcp_credentials_missing",
                extra={"api_key_env_var": api_key_env_var},
            )
        return MCPAuthContext(
            auth_headers=({DEFAULT_MCP_API_KEY_HEADER: api_key} if token_present else {}),
            provider_name=self.provider_name,
            api_key_env_var=api_key_env_var,
            token_present=token_present,
            credentials_configured=token_present,
            credential_source="api_key_env_var",
        )

    def _resolve_env_secret(self, env_var: str, *, require_token: bool) -> str:
        secret_reference = build_env_secret_reference(env_var)
        try:
            resolved = get_secret_resolver().resolve(secret_reference, allow_bare_env=False)
        except SecretResolutionError as exc:
            if require_token or exc.code not in {"secret_unavailable"}:
                raise AppError(
                    "MCP connector credentials are not configured for this environment.",
                    status_code=503,
                    code="mcp_credentials_missing",
                ) from exc
            return ""
        return str(resolved.value or "").strip()


class ConfiguredMCPAuthProvider:
    provider_name = "configured"

    def __init__(
        self,
        *,
        none_provider: MCPAuthProvider | None = None,
        bearer_provider: MCPAuthProvider | None = None,
        api_key_provider: MCPAuthProvider | None = None,
    ) -> None:
        self.none_provider = none_provider or NoAuthMCPAuthProvider()
        self.bearer_provider = bearer_provider or BearerEnvironmentMCPAuthProvider()
        self.api_key_provider = api_key_provider or APIKeyEnvironmentMCPAuthProvider()

    def get_auth_context(
        self,
        config: dict,
        *,
        require_token: bool = True,
        base_url: str | None = None,
    ) -> MCPAuthContext:
        auth_mode = str((config or {}).get("auth_mode") or MCP_AUTH_MODE_NONE).strip().lower()
        if auth_mode == MCP_AUTH_MODE_NONE:
            return self.none_provider.get_auth_context(
                config,
                require_token=require_token,
                base_url=base_url,
            )
        if auth_mode == MCP_AUTH_MODE_BEARER_ENV:
            return self.bearer_provider.get_auth_context(
                config,
                require_token=require_token,
                base_url=base_url,
            )
        if auth_mode == MCP_AUTH_MODE_API_KEY_ENV:
            return self.api_key_provider.get_auth_context(
                config,
                require_token=require_token,
                base_url=base_url,
            )
        raise AppError(
            "MCP auth_mode is not supported in this build.",
            status_code=422,
            code="mcp_auth_mode_unsupported",
        )
