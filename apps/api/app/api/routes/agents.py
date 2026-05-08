from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.core.enums import AgentEnvironment, AgentStatus, AuditActorType, UserRole
from app.core.errors import AppError
from app.core.security import AGENT_API_KEY_SCOPE_GATEWAY_INVOKE, generate_api_key
from app.db.session import get_db
from app.models import Agent, AgentAPIKey, User
from app.models.base import utcnow
from app.schemas.agent import (
    AgentAPIKeyCreate,
    AgentAPIKeyResponse,
    AgentAPIKeySummary,
    AgentCreate,
    AgentResponse,
    AgentUpdate,
)
from app.schemas.common import MessageResponse
from app.services.audit_service import AuditService

router = APIRouter()
audit_service = AuditService()


def _get_tenant_user(db: Session, *, tenant_id: str, user_id: str | None) -> User | None:
    if not user_id:
        return None
    return db.scalar(select(User).where(User.id == user_id, User.tenant_id == tenant_id))


def _assert_agent_write_access(current_user: User, agent: Agent | None = None, owner_user_id: str | None = None) -> None:
    if current_user.role in {UserRole.OWNER, UserRole.ADMIN}:
        return
    if current_user.role == UserRole.DEVELOPER:
        expected_owner_id = owner_user_id if owner_user_id is not None else agent.owner_user_id if agent else None
        if expected_owner_id == current_user.id:
            return
    raise AppError("You do not have write access to this agent.", status_code=403, code="agent_access_forbidden")


def _assert_agent_api_key_read_access(current_user: User, agent: Agent) -> None:
    if current_user.role in {UserRole.OWNER, UserRole.ADMIN, UserRole.SECURITY_REVIEWER}:
        return
    if current_user.role == UserRole.DEVELOPER and agent.owner_user_id == current_user.id:
        return
    raise AppError("You do not have access to this agent's API keys.", status_code=403, code="agent_key_access_forbidden")


@router.get("", response_model=list[AgentResponse])
def list_agents(
    environment: AgentEnvironment | None = Query(default=None),
    status_filter: AgentStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[AgentResponse]:
    query = select(Agent).where(Agent.tenant_id == current_user.tenant_id)
    if environment:
        query = query.where(Agent.environment == environment)
    if status_filter:
        query = query.where(Agent.status == status_filter)
    return [
        AgentResponse.model_validate(item)
        for item in db.scalars(query.order_by(Agent.created_at.desc()).offset(offset).limit(limit))
    ]


@router.post("", response_model=AgentResponse, status_code=status.HTTP_201_CREATED)
def create_agent(
    payload: AgentCreate,
    current_user=Depends(require_roles(UserRole.OWNER, UserRole.ADMIN, UserRole.DEVELOPER)),
    db: Session = Depends(get_db),
) -> AgentResponse:
    owner_user_id = payload.owner_user_id or current_user.id
    owner = _get_tenant_user(db, tenant_id=current_user.tenant_id, user_id=owner_user_id)
    if not owner:
        raise AppError("Owner user not found in tenant.", status_code=404, code="owner_not_found")
    _assert_agent_write_access(current_user, owner_user_id=owner.id)

    agent = Agent(tenant_id=current_user.tenant_id, status=AgentStatus.ACTIVE, **payload.model_dump())
    agent.owner_user_id = owner.id
    db.add(agent)
    db.commit()
    db.refresh(agent)
    audit_service.create_event(
        db,
        tenant_id=current_user.tenant_id,
        actor_type=AuditActorType.USER,
        actor_id=current_user.id,
        event_type="agent.created",
        resource_type="agent",
        resource_id=agent.id,
        metadata={"environment": agent.environment.value, "owner_user_id": agent.owner_user_id},
    )
    db.commit()
    return AgentResponse.model_validate(agent)


@router.get("/{agent_id}", response_model=AgentResponse)
def get_agent(agent_id: str, current_user=Depends(get_current_user), db: Session = Depends(get_db)) -> AgentResponse:
    agent = db.scalar(select(Agent).where(Agent.id == agent_id, Agent.tenant_id == current_user.tenant_id))
    if not agent:
        raise AppError("Agent not found.", status_code=404, code="agent_not_found")
    return AgentResponse.model_validate(agent)


@router.put("/{agent_id}", response_model=AgentResponse)
def update_agent(
    agent_id: str,
    payload: AgentUpdate,
    current_user=Depends(require_roles(UserRole.OWNER, UserRole.ADMIN, UserRole.DEVELOPER)),
    db: Session = Depends(get_db),
) -> AgentResponse:
    agent = db.scalar(select(Agent).where(Agent.id == agent_id, Agent.tenant_id == current_user.tenant_id))
    if not agent:
        raise AppError("Agent not found.", status_code=404, code="agent_not_found")
    _assert_agent_write_access(current_user, agent=agent)
    updates = payload.model_dump(exclude_unset=True)
    if "owner_user_id" in updates and updates["owner_user_id"]:
        owner = _get_tenant_user(db, tenant_id=current_user.tenant_id, user_id=updates["owner_user_id"])
        if not owner:
            raise AppError("Owner user not found in tenant.", status_code=404, code="owner_not_found")
        _assert_agent_write_access(current_user, agent=agent, owner_user_id=owner.id)
    for key, value in updates.items():
        setattr(agent, key, value)
    db.commit()
    db.refresh(agent)
    audit_service.create_event(
        db,
        tenant_id=current_user.tenant_id,
        actor_type=AuditActorType.USER,
        actor_id=current_user.id,
        event_type="agent.updated",
        resource_type="agent",
        resource_id=agent.id,
        metadata={"updated_fields": sorted(updates.keys())},
    )
    db.commit()
    return AgentResponse.model_validate(agent)


@router.post("/{agent_id}/suspend", response_model=AgentResponse)
def suspend_agent(
    agent_id: str,
    current_user=Depends(require_roles(UserRole.OWNER, UserRole.ADMIN)),
    db: Session = Depends(get_db),
) -> AgentResponse:
    agent = db.scalar(select(Agent).where(Agent.id == agent_id, Agent.tenant_id == current_user.tenant_id))
    if not agent:
        raise AppError("Agent not found.", status_code=404, code="agent_not_found")
    agent.status = AgentStatus.SUSPENDED
    db.commit()
    db.refresh(agent)
    audit_service.create_event(
        db,
        tenant_id=current_user.tenant_id,
        actor_type=AuditActorType.USER,
        actor_id=current_user.id,
        event_type="agent.suspended",
        resource_type="agent",
        resource_id=agent.id,
        metadata={"status": agent.status.value},
    )
    db.commit()
    return AgentResponse.model_validate(agent)


@router.post("/{agent_id}/revoke", response_model=AgentResponse)
def revoke_agent(
    agent_id: str,
    current_user=Depends(require_roles(UserRole.OWNER, UserRole.ADMIN)),
    db: Session = Depends(get_db),
) -> AgentResponse:
    agent = db.scalar(select(Agent).where(Agent.id == agent_id, Agent.tenant_id == current_user.tenant_id))
    if not agent:
        raise AppError("Agent not found.", status_code=404, code="agent_not_found")
    agent.status = AgentStatus.REVOKED
    db.commit()
    db.refresh(agent)
    audit_service.create_event(
        db,
        tenant_id=current_user.tenant_id,
        actor_type=AuditActorType.USER,
        actor_id=current_user.id,
        event_type="agent.revoked",
        resource_type="agent",
        resource_id=agent.id,
        metadata={"status": agent.status.value},
    )
    db.commit()
    return AgentResponse.model_validate(agent)


@router.post("/{agent_id}/api-keys", response_model=AgentAPIKeyResponse, status_code=status.HTTP_201_CREATED)
def create_agent_api_key(
    agent_id: str,
    payload: AgentAPIKeyCreate,
    current_user=Depends(require_roles(UserRole.OWNER, UserRole.ADMIN, UserRole.DEVELOPER)),
    db: Session = Depends(get_db),
) -> AgentAPIKeyResponse:
    agent = db.scalar(select(Agent).where(Agent.id == agent_id, Agent.tenant_id == current_user.tenant_id))
    if not agent:
        raise AppError("Agent not found.", status_code=404, code="agent_not_found")
    _assert_agent_write_access(current_user, agent=agent)
    if payload.expires_in_days is None and current_user.role == UserRole.DEVELOPER:
        raise AppError(
            "Developers cannot create non-expiring API keys.",
            status_code=403,
            code="non_expiring_key_forbidden",
        )
    raw_key, prefix, hashed_key = generate_api_key()
    api_key = AgentAPIKey(
        tenant_id=current_user.tenant_id,
        agent_id=agent.id,
        created_by_user_id=current_user.id,
        name=payload.name,
        prefix=prefix,
        hashed_key=hashed_key,
        scopes=payload.scopes or [AGENT_API_KEY_SCOPE_GATEWAY_INVOKE],
        expires_at=(utcnow() + timedelta(days=payload.expires_in_days)) if payload.expires_in_days else None,
    )
    db.add(api_key)
    db.commit()
    db.refresh(api_key)
    audit_service.create_event(
        db,
        tenant_id=current_user.tenant_id,
        actor_type=AuditActorType.USER,
        actor_id=current_user.id,
        event_type="agent.api_key.created",
        resource_type="agent_api_key",
        resource_id=api_key.id,
        metadata={
            "agent_id": agent.id,
            "prefix": api_key.prefix,
            "scopes": api_key.scopes,
            "expires_at": api_key.expires_at.isoformat() if api_key.expires_at else None,
        },
    )
    db.commit()
    return AgentAPIKeyResponse(
        id=api_key.id,
        name=api_key.name,
        prefix=api_key.prefix,
        api_key=raw_key,
        created_at=api_key.created_at,
        created_by_user_id=api_key.created_by_user_id,
        scopes=api_key.scopes,
        expires_at=api_key.expires_at,
        last_used_at=api_key.last_used_at,
        revoked_at=api_key.revoked_at,
    )


@router.get("/{agent_id}/api-keys", response_model=list[AgentAPIKeySummary])
def list_agent_api_keys(
    agent_id: str,
    current_user=Depends(require_roles(UserRole.OWNER, UserRole.ADMIN, UserRole.SECURITY_REVIEWER, UserRole.DEVELOPER)),
    db: Session = Depends(get_db),
) -> list[AgentAPIKeySummary]:
    agent = db.scalar(select(Agent).where(Agent.id == agent_id, Agent.tenant_id == current_user.tenant_id))
    if not agent:
        raise AppError("Agent not found.", status_code=404, code="agent_not_found")
    _assert_agent_api_key_read_access(current_user, agent)
    api_keys = list(
        db.scalars(
            select(AgentAPIKey)
            .where(
                AgentAPIKey.agent_id == agent.id,
                AgentAPIKey.tenant_id == current_user.tenant_id,
            )
            .order_by(AgentAPIKey.created_at.desc())
        )
    )
    return [
        AgentAPIKeySummary(
            id=item.id,
            name=item.name,
            prefix=item.prefix,
            created_at=item.created_at,
            created_by_user_id=item.created_by_user_id,
            scopes=item.scopes,
            expires_at=item.expires_at,
            last_used_at=item.last_used_at,
            revoked_at=item.revoked_at,
        )
        for item in api_keys
    ]


@router.post(
    "/{agent_id}/api-keys/{api_key_id}/revoke",
    response_model=MessageResponse,
)
def revoke_agent_api_key(
    agent_id: str,
    api_key_id: str,
    current_user=Depends(require_roles(UserRole.OWNER, UserRole.ADMIN, UserRole.DEVELOPER)),
    db: Session = Depends(get_db),
) -> MessageResponse:
    agent = db.scalar(select(Agent).where(Agent.id == agent_id, Agent.tenant_id == current_user.tenant_id))
    if not agent:
        raise AppError("Agent not found.", status_code=404, code="agent_not_found")
    _assert_agent_write_access(current_user, agent=agent)

    api_key = db.scalar(
        select(AgentAPIKey).where(
            AgentAPIKey.id == api_key_id,
            AgentAPIKey.agent_id == agent.id,
            AgentAPIKey.tenant_id == current_user.tenant_id,
        )
    )
    if not api_key:
        raise AppError("API key not found.", status_code=404, code="api_key_not_found")
    if api_key.revoked_at is not None:
        raise AppError("API key is already revoked.", status_code=409, code="api_key_already_revoked")

    api_key.revoked_at = utcnow()
    db.commit()
    audit_service.create_event(
        db,
        tenant_id=current_user.tenant_id,
        actor_type=AuditActorType.USER,
        actor_id=current_user.id,
        event_type="agent.api_key.revoked",
        resource_type="agent_api_key",
        resource_id=api_key.id,
        metadata={
            "agent_id": agent.id,
            "prefix": api_key.prefix,
            "revoked_at": api_key.revoked_at.isoformat() if api_key.revoked_at else None,
        },
    )
    db.commit()
    return MessageResponse(message="API key revoked.")
