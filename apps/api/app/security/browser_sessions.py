from __future__ import annotations

import hmac

from fastapi import Request
from starlette.responses import Response

from app.core.config import get_settings
from app.core.errors import AppError
from app.core.security import create_csrf_token, decode_access_token, decode_csrf_token

AUTH_SESSION_MODE_TOKEN = "token"
AUTH_SESSION_MODE_COOKIE = "cookie"
SESSION_COOKIE_NAME = "agentgate_session"
CSRF_COOKIE_NAME = "agentgate_csrf"
CSRF_HEADER_NAME = "X-CSRF-Token"
COOKIE_PATH = "/"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}
CSRF_EXEMPT_PATHS = {
    "/v1/auth/bootstrap",
    "/v1/auth/login",
    "/v1/auth/oidc/exchange",
}


def is_cookie_session_mode() -> bool:
    return get_settings().auth_session_mode == AUTH_SESSION_MODE_COOKIE


def get_session_cookie_token(request: Request) -> str | None:
    if not is_cookie_session_mode():
        return None
    token = request.cookies.get(SESSION_COOKIE_NAME)
    normalized = str(token or "").strip()
    return normalized or None


def issue_session_cookies(response: Response, *, access_token: str) -> str:
    settings = get_settings()
    csrf_token = create_csrf_token(session_token=access_token)
    max_age = int(settings.access_token_expire_minutes) * 60
    cookie_options = {
        "path": COOKIE_PATH,
        "domain": settings.cookie_domain,
        "secure": settings.cookie_secure,
        "samesite": settings.cookie_samesite,
        "max_age": max_age,
    }
    response.set_cookie(
        SESSION_COOKIE_NAME,
        access_token,
        httponly=True,
        **cookie_options,
    )
    response.set_cookie(
        CSRF_COOKIE_NAME,
        csrf_token,
        httponly=True,
        **cookie_options,
    )
    return csrf_token


def clear_session_cookies(response: Response) -> None:
    settings = get_settings()
    delete_options = {
        "path": COOKIE_PATH,
        "domain": settings.cookie_domain,
        "secure": settings.cookie_secure,
        "samesite": settings.cookie_samesite,
    }
    response.delete_cookie(SESSION_COOKIE_NAME, httponly=True, **delete_options)
    response.delete_cookie(CSRF_COOKIE_NAME, httponly=True, **delete_options)


def should_enforce_csrf(request: Request) -> bool:
    settings = get_settings()
    if not settings.csrf_enabled or not is_cookie_session_mode():
        return False
    if request.method.upper() in SAFE_METHODS:
        return False
    if request.url.path in CSRF_EXEMPT_PATHS:
        return False
    if str(request.headers.get("X-API-Key") or "").strip():
        return False
    authorization = str(request.headers.get("Authorization") or "").strip()
    if authorization.lower().startswith("bearer "):
        return False
    session_token = get_session_cookie_token(request)
    if not session_token:
        return False
    try:
        decode_access_token(session_token)
    except AppError:
        # Let the normal auth dependency return the 401.
        return False
    return True


def validate_csrf_request(request: Request) -> None:
    session_token = get_session_cookie_token(request)
    if not session_token:
        return

    csrf_cookie = str(request.cookies.get(CSRF_COOKIE_NAME) or "").strip()
    csrf_header = str(request.headers.get(CSRF_HEADER_NAME) or "").strip()
    if not csrf_cookie or not csrf_header:
        raise AppError("CSRF token required.", status_code=403, code="csrf_required")
    if not hmac.compare_digest(csrf_cookie, csrf_header):
        raise AppError("CSRF token validation failed.", status_code=403, code="csrf_invalid")
    decode_csrf_token(csrf_header, session_token=session_token)
