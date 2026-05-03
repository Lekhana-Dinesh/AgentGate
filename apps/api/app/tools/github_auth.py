from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.core.errors import AppError
from app.security.secret_references import (
    SecretResolutionError,
    build_env_secret_reference,
    get_secret_resolver,
)

DEFAULT_GITHUB_TOKEN_ENV_VAR = "AGENTGATE_GITHUB_TOKEN"


@dataclass(slots=True)
class GitHubAuthContext:
    auth_headers: dict[str, str]
    provider_name: str
    token_env_var: str
    secret_reference: str
    token_present: bool


class GitHubAuthProvider(Protocol):
    provider_name: str

    def get_auth_context(self, config: dict, *, require_token: bool = True) -> GitHubAuthContext:
        ...


class EnvironmentTokenAuthProvider:
    provider_name = "env_pat"

    def get_auth_context(self, config: dict, *, require_token: bool = True) -> GitHubAuthContext:
        token_env_var = str((config or {}).get("token_env_var") or DEFAULT_GITHUB_TOKEN_ENV_VAR).strip()
        secret_reference = build_env_secret_reference(token_env_var)
        token = ""
        token_present = False
        try:
            resolved = get_secret_resolver().resolve(secret_reference, allow_bare_env=False)
            token = resolved.value
            token_present = True
        except SecretResolutionError as exc:
            if require_token or exc.code not in {"secret_unavailable"}:
                raise AppError(
                    "GitHub connector credentials are not configured for this environment.",
                    status_code=503,
                    code="github_credentials_missing",
                    extra={"token_env_var": token_env_var, "secret_reference": secret_reference},
                ) from exc
        if require_token and not token_present:
            raise AppError(
                "GitHub connector credentials are not configured for this environment.",
                status_code=503,
                code="github_credentials_missing",
                extra={"token_env_var": token_env_var, "secret_reference": secret_reference},
            )
        return GitHubAuthContext(
            auth_headers=({"Authorization": f"Bearer {token}"} if token_present else {}),
            provider_name=self.provider_name,
            token_env_var=token_env_var,
            secret_reference=secret_reference,
            token_present=token_present,
        )
