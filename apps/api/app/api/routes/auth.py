from __future__ import annotations

from fastapi import APIRouter, Cookie, Depends, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.core.config import get_settings
from app.core.enums import AuditActorType, UserRole
from app.core.errors import AppError
from app.core.security import decode_access_token
from app.db.session import get_db
from app.schemas.auth import (
    BootstrapOwnerRequest,
    CSRFTokenResponse,
    CreateUserRequest,
    LoginRequest,
    LogoutResponse,
    OIDCConfigStatusResponse,
    OIDCExchangeRequest,
    TokenResponse,
)
from app.security.browser_sessions import (
    AUTH_SESSION_MODE_COOKIE,
    clear_session_cookies,
    get_session_cookie_token,
    issue_session_cookies,
    is_cookie_session_mode,
)
from app.schemas.user import UserResponse
from app.services.audit_service import AuditService
from app.services.auth_service import AuthService
from app.services.oidc_service import OIDC_STATE_COOKIE, OIDCService, build_oidc_frontend_redirect
from app.services.rate_limit_service import get_rate_limiter, get_rate_limit_settings

router = APIRouter()
auth_service = AuthService()
audit_service = AuditService()
oidc_service = OIDCService()


def _oidc_cookie_secure() -> bool:
    settings = get_settings()
    return (
        settings.cookie_secure
        or settings.public_api_url.startswith("https://")
        or settings.public_app_url.startswith("https://")
    )


def _build_auth_response(response: Response, *, access_token: str) -> TokenResponse:
    if is_cookie_session_mode():
        csrf_token = issue_session_cookies(response, access_token=access_token)
        return TokenResponse(
            access_token=None,
            token_type="bearer",
            session_mode=AUTH_SESSION_MODE_COOKIE,
            csrf_token=csrf_token,
        )
    return TokenResponse(access_token=access_token, token_type="bearer", session_mode="token")


@router.post("/bootstrap", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def bootstrap_owner(
    payload: BootstrapOwnerRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> TokenResponse:
    access_token = auth_service.bootstrap_owner(db, payload)
    token_payload = decode_access_token(access_token)
    request.state.tenant_id = token_payload.tenant_id
    request.state.user_id = token_payload.sub
    audit_service.create_event(
        db,
        tenant_id=token_payload.tenant_id,
        actor_type=AuditActorType.USER,
        actor_id=token_payload.sub,
        event_type="auth.bootstrap_owner",
        resource_type="tenant",
        resource_id=token_payload.tenant_id,
        metadata={"email": payload.email.lower()},
    )
    db.commit()
    return _build_auth_response(response, access_token=access_token)


@router.post("/login", response_model=TokenResponse)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> TokenResponse:
    get_rate_limiter().enforce(
        scope="login",
        key_parts=[
            request.client.host if request.client else None,
            payload.tenant_slug,
            payload.email,
        ],
        settings=get_rate_limit_settings("login"),
    )
    access_token = auth_service.login(db, payload)
    token_payload = decode_access_token(access_token)
    request.state.tenant_id = token_payload.tenant_id
    request.state.user_id = token_payload.sub
    audit_service.create_event(
        db,
        tenant_id=token_payload.tenant_id,
        actor_type=AuditActorType.USER,
        actor_id=token_payload.sub,
        event_type="auth.login.success",
        resource_type="user",
        resource_id=token_payload.sub,
        metadata={"tenant_slug": payload.tenant_slug},
    )
    db.commit()
    return _build_auth_response(response, access_token=access_token)


@router.get("/oidc/{tenant_slug}/config-status", response_model=OIDCConfigStatusResponse)
def oidc_config_status(tenant_slug: str, db: Session = Depends(get_db)) -> OIDCConfigStatusResponse:
    return oidc_service.get_config_status(db, tenant_slug=tenant_slug)


@router.get("/oidc/{tenant_slug}/login")
def oidc_login(
    tenant_slug: str,
    request: Request,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    get_rate_limiter().enforce(
        scope="oidc",
        key_parts=[
            request.client.host if request.client else None,
            tenant_slug,
            "login",
        ],
        settings=get_rate_limit_settings("oidc"),
    )
    try:
        initiation = oidc_service.initiate_login(db, tenant_slug=tenant_slug)
        response = RedirectResponse(url=initiation.authorization_url, status_code=status.HTTP_302_FOUND)
        response.set_cookie(
            OIDC_STATE_COOKIE,
            initiation.state_token,
            httponly=True,
            secure=_oidc_cookie_secure(),
            samesite="lax",
            path="/v1/auth/oidc",
        )
        return response
    except AppError as exc:
        return RedirectResponse(
            url=build_oidc_frontend_redirect(tenant_slug=tenant_slug, error_code=exc.code),
            status_code=status.HTTP_302_FOUND,
        )


@router.get("/oidc/{tenant_slug}/callback")
def oidc_callback(
    tenant_slug: str,
    request: Request,
    state: str | None = None,
    code: str | None = None,
    oidc_state_cookie: str | None = Cookie(default=None, alias=OIDC_STATE_COOKIE),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    get_rate_limiter().enforce(
        scope="oidc",
        key_parts=[
            request.client.host if request.client else None,
            tenant_slug,
            "callback",
        ],
        settings=get_rate_limit_settings("oidc"),
    )
    try:
        completion = oidc_service.handle_callback(
            db,
            tenant_slug=tenant_slug,
            state_token=state,
            state_cookie=oidc_state_cookie,
            code=code,
            ip_address=request.client.host if request.client else None,
        )
        redirect_url = build_oidc_frontend_redirect(
            tenant_slug=completion.tenant_slug,
            ticket=completion.exchange_ticket,
        )
    except AppError as exc:
        redirect_url = build_oidc_frontend_redirect(tenant_slug=tenant_slug, error_code=exc.code)
    response = RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)
    response.delete_cookie(OIDC_STATE_COOKIE, path="/v1/auth/oidc")
    return response


@router.post("/oidc/exchange", response_model=TokenResponse)
def exchange_oidc_ticket(
    payload: OIDCExchangeRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> TokenResponse:
    get_rate_limiter().enforce(
        scope="oidc",
        key_parts=[
            request.client.host if request.client else None,
            payload.ticket,
            "exchange",
        ],
        settings=get_rate_limit_settings("oidc"),
    )
    access_token = oidc_service.exchange_ticket(db, ticket=payload.ticket)
    token_payload = decode_access_token(access_token)
    request.state.tenant_id = token_payload.tenant_id
    request.state.user_id = token_payload.sub
    return _build_auth_response(response, access_token=access_token)


@router.get("/me", response_model=UserResponse)
def me(user=Depends(get_current_user)) -> UserResponse:
    return UserResponse.model_validate(user)


@router.post("/logout", response_model=LogoutResponse)
def logout(response: Response) -> LogoutResponse:
    clear_session_cookies(response)
    return LogoutResponse()


@router.get("/csrf-token", response_model=CSRFTokenResponse)
def get_csrf_token(
    request: Request,
    response: Response,
    user=Depends(get_current_user),
) -> CSRFTokenResponse:
    if not is_cookie_session_mode():
        return CSRFTokenResponse(session_mode="token")
    session_token = get_session_cookie_token(request)
    if not session_token:
        raise AppError("Cookie session mode is not active for this request.", status_code=400, code="cookie_session_required")
    del user
    csrf_token = issue_session_cookies(response, access_token=session_token)
    return CSRFTokenResponse(
        csrf_token=csrf_token,
        session_mode=AUTH_SESSION_MODE_COOKIE,
    )


@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: CreateUserRequest,
    current_user=Depends(require_roles(UserRole.OWNER, UserRole.ADMIN)),
    db: Session = Depends(get_db),
) -> UserResponse:
    if payload.role == UserRole.OWNER and current_user.role != UserRole.OWNER:
        raise AppError(
            "Only tenant owners can create another owner account.",
            status_code=403,
            code="owner_creation_forbidden",
        )
    user = auth_service.create_user(db, current_user.tenant_id, payload)
    audit_service.create_event(
        db,
        tenant_id=current_user.tenant_id,
        actor_type=AuditActorType.USER,
        actor_id=current_user.id,
        event_type="auth.user.created",
        resource_type="user",
        resource_id=user.id,
        metadata={"created_role": user.role.value},
    )
    db.commit()
    return UserResponse.model_validate(user)
