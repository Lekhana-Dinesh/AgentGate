from __future__ import annotations

from dataclasses import dataclass
from datetime import timezone
from typing import Callable

from fastapi import Depends, Header, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import AuditActorType, UserRole
from app.core.errors import AppError
from app.core.security import AGENT_API_KEY_SCOPE_GATEWAY_INVOKE, decode_access_token, verify_api_key
from app.db.session import get_db
from app.models import AgentAPIKey, User
from app.models.base import utcnow


@dataclass(slots=True)
class Principal:
    tenant_id: str
    actor_type: AuditActorType
    actor_id: str | None
    role: UserRole | None
    user: User | None = None
    api_key: AgentAPIKey | None = None
    agent_id: str | None = None


def _normalize_datetime(value):
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _extract_bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    if not authorization.lower().startswith("bearer "):
        return None
    return authorization.split(" ", 1)[1].strip()


def _bind_request_context(
    request: Request | None,
    *,
    tenant_id: str | None,
    user_id: str | None = None,
) -> None:
    if request is None:
        return
    request.state.tenant_id = tenant_id
    request.state.user_id = user_id


def get_current_user(
    request: Request,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    token = _extract_bearer_token(authorization)
    if not token:
        raise AppError("Authentication required.", status_code=401, code="authentication_required")

    payload = decode_access_token(token)
    user = db.scalar(
        select(User).where(User.id == payload.sub, User.tenant_id == payload.tenant_id)
    )
    if not user or not user.is_active:
        raise AppError("User is not active.", status_code=401, code="inactive_user")
    _bind_request_context(request, tenant_id=user.tenant_id, user_id=user.id)
    return user


def require_roles(*roles: UserRole) -> Callable:
    def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise AppError("Insufficient permissions.", status_code=403, code="forbidden")
        return user

    return dependency


def get_gateway_principal(
    request: Request,
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> Principal:
    if x_api_key:
        prefix = x_api_key.split(".", 1)[0]
        api_key = db.scalar(
            select(AgentAPIKey).where(
                AgentAPIKey.prefix == prefix,
                AgentAPIKey.revoked_at.is_(None),
            )
        )
        if not api_key or not verify_api_key(x_api_key, api_key.hashed_key):
            raise AppError("Invalid API key.", status_code=401, code="invalid_api_key")
        expires_at = _normalize_datetime(api_key.expires_at)
        if expires_at and expires_at <= utcnow():
            raise AppError("API key has expired.", status_code=401, code="api_key_expired")
        if AGENT_API_KEY_SCOPE_GATEWAY_INVOKE not in (api_key.scopes or []):
            raise AppError(
                "API key does not grant gateway invocation scope.",
                status_code=403,
                code="api_key_scope_forbidden",
            )
        api_key.last_used_at = utcnow()
        _bind_request_context(request, tenant_id=api_key.tenant_id, user_id=None)
        return Principal(
            tenant_id=api_key.tenant_id,
            actor_type=AuditActorType.AGENT,
            actor_id=api_key.agent_id,
            role=None,
            api_key=api_key,
            agent_id=api_key.agent_id,
        )

    user = get_current_user(request=request, authorization=authorization, db=db)
    return Principal(
        tenant_id=user.tenant_id,
        actor_type=AuditActorType.USER,
        actor_id=user.id,
        role=user.role,
        user=user,
    )
