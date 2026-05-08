from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from argon2 import PasswordHasher

from app.core.config import get_settings
from app.core.errors import AppError

password_hasher = PasswordHasher()
AGENT_API_KEY_SCOPE_GATEWAY_INVOKE = "gateway:invoke"
SUPPORTED_AGENT_API_KEY_SCOPES = {AGENT_API_KEY_SCOPE_GATEWAY_INVOKE}


@dataclass(slots=True)
class TokenPayload:
    sub: str
    tenant_id: str
    role: str
    exp: int


@dataclass(slots=True)
class OIDCStatePayload:
    tenant_id: str
    tenant_slug: str
    config_id: str
    nonce: str
    exp: int


@dataclass(slots=True)
class OIDCExchangeTicketPayload:
    sub: str
    tenant_id: str
    role: str
    exp: int


@dataclass(slots=True)
class CSRFTokenPayload:
    sub: str
    tenant_id: str
    session_fingerprint: str
    exp: int


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    try:
        return password_hasher.verify(hashed_password, password)
    except Exception:
        return False


def create_access_token(*, user_id: str, tenant_id: str, role: str) -> str:
    settings = get_settings()
    expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=settings.access_token_expire_minutes
    )
    payload = {
        "sub": user_id,
        "tenant_id": tenant_id,
        "role": role,
        "exp": expires_at,
    }
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def create_oidc_state_token(
    *,
    tenant_id: str,
    tenant_slug: str,
    config_id: str,
    nonce: str,
) -> str:
    settings = get_settings()
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=settings.oidc_state_ttl_seconds)
    payload = {
        "purpose": "oidc_state",
        "tenant_id": tenant_id,
        "tenant_slug": tenant_slug,
        "config_id": config_id,
        "nonce": nonce,
        "exp": expires_at,
    }
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def decode_oidc_state_token(token: str) -> OIDCStatePayload:
    payload = _decode_signed_token(
        token,
        expected_purpose="oidc_state",
        error_code="oidc_invalid_state",
        detail="OIDC state validation failed.",
    )
    return OIDCStatePayload(
        tenant_id=payload["tenant_id"],
        tenant_slug=payload["tenant_slug"],
        config_id=payload["config_id"],
        nonce=payload["nonce"],
        exp=payload["exp"],
    )


def create_oidc_exchange_ticket(*, user_id: str, tenant_id: str, role: str) -> str:
    settings = get_settings()
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=settings.oidc_exchange_ttl_seconds)
    payload = {
        "purpose": "oidc_exchange",
        "sub": user_id,
        "tenant_id": tenant_id,
        "role": role,
        "exp": expires_at,
    }
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def decode_oidc_exchange_ticket(ticket: str) -> OIDCExchangeTicketPayload:
    payload = _decode_signed_token(
        ticket,
        expected_purpose="oidc_exchange",
        error_code="oidc_invalid_exchange_ticket",
        detail="OIDC login exchange could not be completed.",
    )
    return OIDCExchangeTicketPayload(
        sub=payload["sub"],
        tenant_id=payload["tenant_id"],
        role=payload["role"],
        exp=payload["exp"],
    )


def decode_access_token(token: str) -> TokenPayload:
    payload = _decode_signed_token(
        token,
        expected_purpose=None,
        error_code="invalid_token",
        detail="Invalid access token.",
    )
    return TokenPayload(
        sub=payload["sub"],
        tenant_id=payload["tenant_id"],
        role=payload["role"],
        exp=payload["exp"],
    )


def create_csrf_token(*, session_token: str) -> str:
    session_payload = decode_access_token(session_token)
    payload = {
        "purpose": "csrf",
        "sub": session_payload.sub,
        "tenant_id": session_payload.tenant_id,
        "session_fingerprint": _token_fingerprint(session_token),
        "exp": datetime.fromtimestamp(session_payload.exp, tz=timezone.utc),
    }
    return jwt.encode(payload, get_settings().secret_key, algorithm="HS256")


def decode_csrf_token(token: str, *, session_token: str) -> CSRFTokenPayload:
    payload = _decode_signed_token(
        token,
        expected_purpose="csrf",
        error_code="csrf_invalid",
        detail="CSRF token validation failed.",
        status_code=403,
    )
    session_payload = decode_access_token(session_token)
    session_fingerprint = _token_fingerprint(session_token)
    if (
        payload["sub"] != session_payload.sub
        or payload["tenant_id"] != session_payload.tenant_id
        or payload["session_fingerprint"] != session_fingerprint
    ):
        raise AppError("CSRF token validation failed.", status_code=403, code="csrf_invalid")
    return CSRFTokenPayload(
        sub=payload["sub"],
        tenant_id=payload["tenant_id"],
        session_fingerprint=payload["session_fingerprint"],
        exp=payload["exp"],
    )


def generate_api_key() -> tuple[str, str, str]:
    raw_secret = secrets.token_urlsafe(32)
    prefix = f"agk_{raw_secret[:8]}"
    raw_key = f"{prefix}.{raw_secret}"
    hashed_key = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    return raw_key, prefix, hashed_key


def verify_api_key(raw_key: str, hashed_key: str) -> bool:
    candidate = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    return hmac.compare_digest(candidate, hashed_key)


def _token_fingerprint(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _decode_signed_token(
    token: str,
    *,
    expected_purpose: str | None,
    error_code: str,
    detail: str,
    status_code: int = 401,
) -> dict[str, Any]:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise AppError(detail, status_code=status_code, code=error_code) from exc
    if expected_purpose and payload.get("purpose") != expected_purpose:
        raise AppError(detail, status_code=status_code, code=error_code)
    return payload
