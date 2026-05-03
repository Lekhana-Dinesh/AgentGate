from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlencode

import httpx
import jwt

from app.core.config import get_settings
from app.core.errors import AppError
from app.security.secret_references import (
    SecretResolutionError,
    build_env_secret_reference,
    get_secret_resolver,
)


@dataclass(slots=True)
class OIDCIdentity:
    subject: str
    email: str
    full_name: str
    issuer: str
    audience: str
    groups: list[str]
    claims: dict[str, Any]


class OIDCProviderClient(Protocol):
    def get_authorization_url(self, config, *, state: str, nonce: str) -> str:
        ...

    def exchange_code_for_identity(self, config, *, code: str, expected_nonce: str) -> OIDCIdentity:
        ...


def resolve_oidc_client_secret(config) -> str:
    env_var = str(config.client_secret_env_var or "").strip()
    if env_var:
        try:
            return get_secret_resolver().resolve(
                build_env_secret_reference(env_var),
                allow_bare_env=False,
            ).value
        except SecretResolutionError as exc:
            raise _map_oidc_secret_resolution_error(exc) from exc

    secret_ref = str(config.client_secret_ref or "").strip()
    if secret_ref:
        try:
            return get_secret_resolver().resolve(secret_ref).value
        except SecretResolutionError as exc:
            raise _map_oidc_secret_resolution_error(exc) from exc

    raise AppError(
        "OIDC client secret is not configured.",
        status_code=503,
        code="oidc_secret_unavailable",
    )


def _map_oidc_secret_resolution_error(exc: SecretResolutionError) -> AppError:
    if exc.code == "secret_provider_unconfigured":
        return AppError(
            "OIDC client secret refs require a configured external secret resolver.",
            status_code=503,
            code="oidc_secret_ref_unsupported",
        )
    if exc.code == "invalid_secret_ref":
        return AppError(
            "OIDC client secret reference is invalid.",
            status_code=503,
            code="oidc_secret_ref_invalid",
        )
    return AppError(
        "OIDC client secret is not available in the configured environment.",
        status_code=503,
        code="oidc_secret_unavailable",
    )


class DiscoveryOIDCProviderClient:
    def __init__(self) -> None:
        self._timeout = get_settings().oidc_http_timeout_seconds

    def get_authorization_url(self, config, *, state: str, nonce: str) -> str:
        discovery = self._fetch_discovery(config.issuer_url)
        authorization_endpoint = str(discovery.get("authorization_endpoint") or "").strip()
        if not authorization_endpoint:
            raise AppError(
                "OIDC provider discovery is missing an authorization endpoint.",
                status_code=503,
                code="oidc_provider_invalid",
            )
        params = {
            "response_type": "code",
            "client_id": config.client_id,
            "redirect_uri": config.redirect_uri,
            "scope": " ".join(config.scopes or ["openid", "profile", "email"]),
            "state": state,
            "nonce": nonce,
        }
        return f"{authorization_endpoint}?{urlencode(params)}"

    def exchange_code_for_identity(self, config, *, code: str, expected_nonce: str) -> OIDCIdentity:
        discovery = self._fetch_discovery(config.issuer_url)
        token_endpoint = str(discovery.get("token_endpoint") or "").strip()
        if not token_endpoint:
            raise AppError(
                "OIDC provider discovery is missing a token endpoint.",
                status_code=503,
                code="oidc_provider_invalid",
            )
        token_payload = self._exchange_code_for_tokens(config, token_endpoint=token_endpoint, code=code)
        id_token = str(token_payload.get("id_token") or "").strip()
        if not id_token:
            raise AppError(
                "OIDC token response did not include an ID token.",
                status_code=401,
                code="oidc_token_invalid",
            )
        validated_claims = self._validate_id_token(
            config,
            id_token=id_token,
            expected_issuer=str(discovery.get("issuer") or config.issuer_url).rstrip("/"),
            jwks_uri=str(discovery.get("jwks_uri") or "").strip(),
            expected_nonce=expected_nonce,
        )
        merged_claims = dict(validated_claims)
        access_token = str(token_payload.get("access_token") or "").strip()
        userinfo_endpoint = str(discovery.get("userinfo_endpoint") or "").strip()
        if access_token and userinfo_endpoint:
            merged_claims.update(self._fetch_userinfo(userinfo_endpoint=userinfo_endpoint, access_token=access_token))

        email = str(merged_claims.get("email") or "").strip().lower()
        if not email:
            raise AppError(
                "OIDC identity is missing an email claim.",
                status_code=401,
                code="oidc_email_missing",
            )
        if merged_claims.get("email_verified") is False:
            raise AppError(
                "OIDC identity email is not verified.",
                status_code=403,
                code="oidc_email_unverified",
            )
        subject = str(merged_claims.get("sub") or "").strip()
        if not subject:
            raise AppError(
                "OIDC identity is missing a subject claim.",
                status_code=401,
                code="oidc_subject_missing",
            )
        full_name = str(
            merged_claims.get("name")
            or merged_claims.get("preferred_username")
            or merged_claims.get("given_name")
            or email
        ).strip()
        return OIDCIdentity(
            subject=subject,
            email=email,
            full_name=full_name or email,
            issuer=str(merged_claims.get("iss") or config.issuer_url).rstrip("/"),
            audience=str(validated_claims.get("aud") or config.client_id),
            groups=self._normalize_groups(merged_claims.get("groups")),
            claims=merged_claims,
        )

    def _fetch_discovery(self, issuer_url: str) -> dict[str, Any]:
        discovery_url = issuer_url.rstrip("/")
        if ".well-known/openid-configuration" not in discovery_url:
            discovery_url = f"{discovery_url}/.well-known/openid-configuration"
        with self._build_client() as client:
            response = client.get(discovery_url)
        if response.status_code != 200:
            raise AppError(
                "OIDC discovery document could not be retrieved.",
                status_code=503,
                code="oidc_discovery_failed",
            )
        payload = response.json()
        if not isinstance(payload, dict):
            raise AppError(
                "OIDC discovery document is invalid.",
                status_code=503,
                code="oidc_provider_invalid",
            )
        return payload

    def _exchange_code_for_tokens(self, config, *, token_endpoint: str, code: str) -> dict[str, Any]:
        client_secret = resolve_oidc_client_secret(config)
        with self._build_client() as client:
            response = client.post(
                token_endpoint,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": config.redirect_uri,
                    "client_id": config.client_id,
                    "client_secret": client_secret,
                },
                headers={"Accept": "application/json"},
            )
        if response.status_code != 200:
            raise AppError(
                "OIDC code exchange failed.",
                status_code=401,
                code="oidc_code_exchange_failed",
            )
        payload = response.json()
        if not isinstance(payload, dict):
            raise AppError(
                "OIDC token response is invalid.",
                status_code=401,
                code="oidc_token_invalid",
            )
        return payload

    def _fetch_userinfo(self, *, userinfo_endpoint: str, access_token: str) -> dict[str, Any]:
        with self._build_client() as client:
            response = client.get(
                userinfo_endpoint,
                headers={"Authorization": f"Bearer {access_token}"},
            )
        if response.status_code != 200:
            raise AppError(
                "OIDC userinfo lookup failed.",
                status_code=401,
                code="oidc_userinfo_failed",
            )
        payload = response.json()
        if not isinstance(payload, dict):
            raise AppError(
                "OIDC userinfo response is invalid.",
                status_code=401,
                code="oidc_userinfo_failed",
            )
        return payload

    def _validate_id_token(
        self,
        config,
        *,
        id_token: str,
        expected_issuer: str,
        jwks_uri: str,
        expected_nonce: str,
    ) -> dict[str, Any]:
        if not jwks_uri:
            raise AppError(
                "OIDC provider discovery is missing a JWKS URI.",
                status_code=503,
                code="oidc_provider_invalid",
            )
        try:
            signing_key = jwt.PyJWKClient(jwks_uri).get_signing_key_from_jwt(id_token)
            claims = jwt.decode(
                id_token,
                signing_key.key,
                algorithms=["RS256", "RS384", "RS512", "ES256", "ES384", "ES512"],
                audience=config.client_id,
                issuer=expected_issuer,
            )
        except jwt.PyJWTError as exc:
            raise AppError(
                "OIDC ID token validation failed.",
                status_code=401,
                code="oidc_token_invalid",
            ) from exc
        if str(claims.get("nonce") or "").strip() != expected_nonce:
            raise AppError(
                "OIDC nonce validation failed.",
                status_code=401,
                code="oidc_invalid_nonce",
            )
        return claims

    def _build_client(self) -> httpx.Client:
        return httpx.Client(timeout=self._timeout, follow_redirects=True)

    def _normalize_groups(self, value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        return []
