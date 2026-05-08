from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from time import time
from typing import Any, Callable, Protocol

import httpx
import jwt

from app.core.errors import AppError
from app.core.redaction import redact_sensitive_string
from app.security.secret_references import (
    LocalSecretResolver,
    SecretResolutionError,
    build_env_secret_reference,
    get_secret_resolver,
)

DEFAULT_GITHUB_TOKEN_ENV_VAR = "AGENTGATE_GITHUB_TOKEN"
DEFAULT_GITHUB_API_BASE_URL = "https://api.github.com"
GITHUB_AUTH_MODE_ENV_PAT = "env_pat"
GITHUB_AUTH_MODE_ENV_TOKEN = "env_token"
GITHUB_AUTH_MODE_GITHUB_APP = "github_app"
GITHUB_ENV_AUTH_MODES = {GITHUB_AUTH_MODE_ENV_PAT, GITHUB_AUTH_MODE_ENV_TOKEN}
DEFAULT_GITHUB_APP_JWT_TTL_SECONDS = 540
DEFAULT_GITHUB_APP_TOKEN_CACHE_TTL_SECONDS = 3000
DEFAULT_GITHUB_APP_REFRESH_SKEW_SECONDS = 60
DEFAULT_GITHUB_AUTH_TIMEOUT_SECONDS = 15.0


@dataclass(slots=True)
class GitHubAuthContext:
    auth_headers: dict[str, str]
    provider_name: str
    token_env_var: str | None = None
    secret_reference: str | None = None
    token_present: bool = False
    credentials_configured: bool = False
    app_id: str | None = None
    installation_id: str | None = None
    private_key_env_var: str | None = None
    private_key_reference_type: str | None = None
    token_expires_at: str | None = None
    cache_hit: bool = False
    credential_source: str | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class _GitHubAppConfig:
    app_id: str
    installation_id: str
    private_key_reference: str
    private_key_env_var: str | None
    private_key_reference_type: str
    token_cache_ttl_seconds: int


@dataclass(frozen=True, slots=True)
class _CachedInstallationToken:
    token: str
    expires_at_timestamp: float
    refresh_at_timestamp: float
    expires_at: str


class GitHubAuthProvider(Protocol):
    provider_name: str

    def get_auth_context(
        self,
        config: dict,
        *,
        require_token: bool = True,
        base_url: str | None = None,
    ) -> GitHubAuthContext:
        ...


class EnvironmentTokenAuthProvider:
    provider_name = GITHUB_AUTH_MODE_ENV_TOKEN

    def get_auth_context(
        self,
        config: dict,
        *,
        require_token: bool = True,
        base_url: str | None = None,  # noqa: ARG002 - signature compatibility
    ) -> GitHubAuthContext:
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
            credentials_configured=token_present,
            credential_source="token_env_var",
        )


class GitHubAppAuthProvider:
    provider_name = GITHUB_AUTH_MODE_GITHUB_APP
    _token_cache: dict[tuple[str, str, str], _CachedInstallationToken] = {}
    _cache_lock = Lock()

    def __init__(
        self,
        *,
        secret_resolver: LocalSecretResolver | None = None,
        client_factory: Callable[..., httpx.Client] | None = None,
        time_source: Callable[[], float] | None = None,
    ) -> None:
        self.secret_resolver = secret_resolver or get_secret_resolver()
        self.client_factory = client_factory
        self.time_source = time_source or time

    @classmethod
    def clear_cache(cls) -> None:
        with cls._cache_lock:
            cls._token_cache.clear()

    def get_auth_context(
        self,
        config: dict,
        *,
        require_token: bool = True,
        base_url: str | None = None,
    ) -> GitHubAuthContext:
        resolved_base_url = base_url or DEFAULT_GITHUB_API_BASE_URL
        app_config = self._resolve_config(config, require_token=require_token)
        if app_config is None:
            return GitHubAuthContext(
                auth_headers={},
                provider_name=self.provider_name,
                credentials_configured=False,
                token_present=False,
                warnings=["GitHub App credentials are not fully configured for this tool."],
                credential_source="github_app",
            )

        cached_token = self._get_cached_installation_token(
            base_url=resolved_base_url,
            app_config=app_config,
        )
        if cached_token is not None:
            return self._build_auth_context(
                app_config=app_config,
                token=cached_token.token,
                token_expires_at=cached_token.expires_at,
                cache_hit=True,
            )

        private_key = self._resolve_private_key(app_config, require_token=require_token)
        if private_key is None:
            return GitHubAuthContext(
                auth_headers={},
                provider_name=self.provider_name,
                credentials_configured=False,
                token_present=False,
                app_id=app_config.app_id,
                installation_id=app_config.installation_id,
                private_key_env_var=app_config.private_key_env_var,
                private_key_reference_type=app_config.private_key_reference_type,
                warnings=["GitHub App private key is not available in this environment."],
                credential_source="github_app",
            )

        self._build_app_jwt(app_config.app_id, private_key)

        if not require_token:
            return self._build_auth_context(
                app_config=app_config,
                token=None,
                token_expires_at=None,
                cache_hit=False,
            )

        token, expires_at, cache_hit = self._get_or_exchange_installation_token(
            base_url=resolved_base_url,
            app_config=app_config,
            private_key=private_key,
        )
        return self._build_auth_context(
            app_config=app_config,
            token=token,
            token_expires_at=expires_at,
            cache_hit=cache_hit,
        )

    def _build_auth_context(
        self,
        *,
        app_config: _GitHubAppConfig,
        token: str | None,
        token_expires_at: str | None,
        cache_hit: bool,
    ) -> GitHubAuthContext:
        return GitHubAuthContext(
            auth_headers=({"Authorization": f"Bearer {token}"} if token else {}),
            provider_name=self.provider_name,
            token_present=bool(token),
            credentials_configured=True,
            app_id=app_config.app_id,
            installation_id=app_config.installation_id,
            private_key_env_var=app_config.private_key_env_var,
            private_key_reference_type=app_config.private_key_reference_type,
            token_expires_at=token_expires_at,
            cache_hit=cache_hit,
            credential_source="github_app",
        )

    def _resolve_config(self, config: dict, *, require_token: bool) -> _GitHubAppConfig | None:
        app_id = str((config or {}).get("app_id") or "").strip()
        installation_id = str((config or {}).get("installation_id") or "").strip()
        private_key_env_var = str((config or {}).get("private_key_env_var") or "").strip() or None
        private_key_secret_ref = str((config or {}).get("private_key_secret_ref") or "").strip() or None
        token_cache_ttl_seconds = int(
            (config or {}).get("token_cache_ttl_seconds") or DEFAULT_GITHUB_APP_TOKEN_CACHE_TTL_SECONDS
        )

        if not app_id or not installation_id or bool(private_key_env_var) == bool(private_key_secret_ref):
            if require_token:
                raise AppError(
                    "GitHub App credentials are not fully configured for this tool.",
                    status_code=503,
                    code="github_app_credentials_missing",
                )
            return None

        if private_key_env_var:
            private_key_reference = build_env_secret_reference(private_key_env_var)
            private_key_reference_type = "env"
        else:
            private_key_reference = str(private_key_secret_ref or "").strip()
            try:
                parsed_reference = self.secret_resolver.parse(private_key_reference, allow_bare_env=False)
            except SecretResolutionError as exc:
                if require_token:
                    raise AppError(
                        "GitHub App private key reference is invalid.",
                        status_code=503,
                        code="github_app_private_key_invalid",
                    ) from exc
                return None
            private_key_reference_type = parsed_reference.reference_type

        return _GitHubAppConfig(
            app_id=app_id,
            installation_id=installation_id,
            private_key_reference=private_key_reference,
            private_key_env_var=private_key_env_var,
            private_key_reference_type=private_key_reference_type,
            token_cache_ttl_seconds=token_cache_ttl_seconds,
        )

    def _resolve_private_key(
        self,
        app_config: _GitHubAppConfig,
        *,
        require_token: bool,
    ) -> str | None:
        try:
            resolved = self.secret_resolver.resolve(app_config.private_key_reference, allow_bare_env=False)
        except SecretResolutionError as exc:
            if require_token:
                raise AppError(
                    "GitHub App private key is not configured for this environment.",
                    status_code=503,
                    code="github_app_credentials_missing",
                ) from exc
            return None

        private_key = str(resolved.value or "").strip()
        if not private_key:
            if require_token:
                raise AppError(
                    "GitHub App private key is not configured for this environment.",
                    status_code=503,
                    code="github_app_credentials_missing",
                )
            return None
        return private_key.replace("\\n", "\n").strip()

    def _build_app_jwt(self, app_id: str, private_key: str) -> str:
        issued_at = int(self.time_source())
        payload = {
            "iat": issued_at - 60,
            "exp": issued_at + DEFAULT_GITHUB_APP_JWT_TTL_SECONDS,
            "iss": app_id,
        }
        try:
            token = jwt.encode(payload, private_key, algorithm="RS256")
        except Exception as exc:
            raise AppError(
                "GitHub App private key is invalid.",
                status_code=503,
                code="github_app_private_key_invalid",
            ) from exc
        return token if isinstance(token, str) else token.decode("utf-8")

    def _get_or_exchange_installation_token(
        self,
        *,
        base_url: str,
        app_config: _GitHubAppConfig,
        private_key: str,
    ) -> tuple[str, str, bool]:
        cached = self._get_cached_installation_token(base_url=base_url, app_config=app_config)
        if cached is not None:
            return cached.token, cached.expires_at, True

        app_jwt = self._build_app_jwt(app_config.app_id, private_key)
        token, expires_at = self._exchange_installation_token(
            base_url=base_url,
            installation_id=app_config.installation_id,
            app_jwt=app_jwt,
        )
        self._store_cached_installation_token(
            base_url=base_url,
            app_config=app_config,
            token=token,
            expires_at=expires_at,
        )
        return token, expires_at, False

    def _get_cached_installation_token(
        self,
        *,
        base_url: str,
        app_config: _GitHubAppConfig,
    ) -> _CachedInstallationToken | None:
        cache_key = self._cache_key(base_url=base_url, app_config=app_config)
        now = float(self.time_source())
        with self._cache_lock:
            cached = self._token_cache.get(cache_key)
            if cached is None:
                return None
            if now >= cached.refresh_at_timestamp:
                if now >= cached.expires_at_timestamp:
                    self._token_cache.pop(cache_key, None)
                return None
            return cached

    def _store_cached_installation_token(
        self,
        *,
        base_url: str,
        app_config: _GitHubAppConfig,
        token: str,
        expires_at: str,
    ) -> None:
        now = float(self.time_source())
        expires_at_timestamp = self._normalized_expiry_timestamp(
            expires_at=expires_at,
            now=now,
            token_cache_ttl_seconds=app_config.token_cache_ttl_seconds,
        )
        effective_ttl = max(1.0, expires_at_timestamp - now)
        refresh_skew = min(
            float(DEFAULT_GITHUB_APP_REFRESH_SKEW_SECONDS),
            max(5.0, effective_ttl * 0.1),
        )
        refresh_at_timestamp = max(now + 1.0, expires_at_timestamp - refresh_skew)
        cache_key = self._cache_key(base_url=base_url, app_config=app_config)
        with self._cache_lock:
            self._token_cache[cache_key] = _CachedInstallationToken(
                token=token,
                expires_at_timestamp=expires_at_timestamp,
                refresh_at_timestamp=refresh_at_timestamp,
                expires_at=expires_at,
            )

    def _normalized_expiry_timestamp(
        self,
        *,
        expires_at: str,
        now: float,
        token_cache_ttl_seconds: int,
    ) -> float:
        try:
            expires_at_timestamp = datetime.fromisoformat(
                str(expires_at or "").replace("Z", "+00:00")
            ).timestamp()
        except ValueError as exc:
            raise AppError(
                "GitHub App installation token response was invalid.",
                status_code=502,
                code="github_request_failed",
            ) from exc
        return min(expires_at_timestamp, now + float(token_cache_ttl_seconds))

    def _exchange_installation_token(
        self,
        *,
        base_url: str,
        installation_id: str,
        app_jwt: str,
    ) -> tuple[str, str]:
        timeout_seconds = DEFAULT_GITHUB_AUTH_TIMEOUT_SECONDS
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "AgentGate/0.1.0",
            "X-GitHub-Api-Version": "2022-11-28",
            "Authorization": f"Bearer {app_jwt}",
        }
        try:
            with self._build_http_client(
                base_url=base_url,
                headers=headers,
                timeout=timeout_seconds,
            ) as client:
                response = client.post(f"/app/installations/{installation_id}/access_tokens")
        except httpx.TimeoutException as exc:
            raise AppError(
                "GitHub did not respond before the connector timeout elapsed.",
                status_code=503,
                code="github_upstream_unavailable",
            ) from exc
        except httpx.RequestError as exc:
            raise AppError(
                "GitHub is temporarily unavailable.",
                status_code=503,
                code="github_upstream_unavailable",
            ) from exc

        if response.status_code >= 400:
            self._raise_upstream_error(response)

        try:
            payload = response.json()
        except ValueError as exc:
            raise AppError(
                "GitHub App installation token response was invalid.",
                status_code=502,
                code="github_request_failed",
            ) from exc

        token = str(payload.get("token") or "").strip()
        expires_at = str(payload.get("expires_at") or "").strip()
        if not token or not expires_at:
            raise AppError(
                "GitHub App installation token response was invalid.",
                status_code=502,
                code="github_request_failed",
            )
        return token, expires_at

    def _raise_upstream_error(self, response: httpx.Response) -> None:
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        message = redact_sensitive_string(str(payload.get("message") or "GitHub request failed."))
        extra = {"github_status_code": response.status_code, "operation": "installation_token_exchange"}

        if response.status_code == 401:
            raise AppError(
                "GitHub authentication failed. Check the configured credentials.",
                status_code=502,
                code="github_auth_failed",
                extra=extra,
            )
        if response.status_code == 403:
            raise AppError(
                message or "GitHub rejected the request.",
                status_code=502,
                code="github_forbidden",
                extra=extra,
            )
        if response.status_code == 404:
            raise AppError(
                "GitHub repository or resource was not found.",
                status_code=404,
                code="github_resource_not_found",
                extra=extra,
            )
        if response.status_code == 429:
            raise AppError(
                "GitHub rate limited the connector request.",
                status_code=503,
                code="github_rate_limited",
                extra=extra,
            )
        if response.status_code >= 500:
            raise AppError(
                "GitHub is temporarily unavailable.",
                status_code=503,
                code="github_upstream_unavailable",
                extra=extra,
            )
        raise AppError(
            message or "GitHub request failed.",
            status_code=400,
            code="github_request_failed",
            extra=extra,
        )

    def _build_http_client(
        self,
        *,
        base_url: str,
        headers: dict[str, str],
        timeout: float,
    ) -> httpx.Client:
        if self.client_factory:
            return self.client_factory(
                base_url=base_url,
                headers=headers,
                timeout=timeout,
            )
        return httpx.Client(
            base_url=base_url,
            headers=headers,
            timeout=timeout,
            follow_redirects=True,
        )

    def _cache_key(self, *, base_url: str, app_config: _GitHubAppConfig) -> tuple[str, str, str]:
        return (
            str(base_url or DEFAULT_GITHUB_API_BASE_URL).rstrip("/").lower(),
            app_config.app_id,
            app_config.installation_id,
        )


class ConfiguredGitHubAuthProvider:
    provider_name = "configured"

    def __init__(
        self,
        *,
        env_provider: GitHubAuthProvider | None = None,
        github_app_provider: GitHubAuthProvider | None = None,
    ) -> None:
        self.env_provider = env_provider or EnvironmentTokenAuthProvider()
        self.github_app_provider = github_app_provider or GitHubAppAuthProvider()

    def get_auth_context(
        self,
        config: dict,
        *,
        require_token: bool = True,
        base_url: str | None = None,
    ) -> GitHubAuthContext:
        auth_mode = str((config or {}).get("auth_mode") or GITHUB_AUTH_MODE_ENV_PAT).strip().lower()
        if auth_mode in GITHUB_ENV_AUTH_MODES:
            return self.env_provider.get_auth_context(
                config,
                require_token=require_token,
                base_url=base_url,
            )
        if auth_mode == GITHUB_AUTH_MODE_GITHUB_APP:
            return self.github_app_provider.get_auth_context(
                config,
                require_token=require_token,
                base_url=base_url,
            )
        raise AppError(
            "GitHub auth_mode is not supported in this build.",
            status_code=422,
            code="github_auth_mode_unsupported",
        )
