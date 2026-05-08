from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.core.enums import AuditActorType, UserRole
from app.core.errors import AppError
from app.db.session import get_db
from app.models import Policy
from app.schemas.policy import PolicyCreate, PolicyResponse, PolicyUpdate
from app.services.audit_service import AuditService

router = APIRouter()
audit_service = AuditService()


@router.get("", response_model=list[PolicyResponse])
def list_policies(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[PolicyResponse]:
    policies = list(
        db.scalars(
            select(Policy)
            .where(Policy.tenant_id == current_user.tenant_id)
            .order_by(Policy.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
    )
    return [PolicyResponse.model_validate(item) for item in policies]


@router.post("", response_model=PolicyResponse, status_code=status.HTTP_201_CREATED)
def create_policy(
    payload: PolicyCreate,
    current_user=Depends(require_roles(UserRole.OWNER, UserRole.ADMIN)),
    db: Session = Depends(get_db),
) -> PolicyResponse:
    policy = Policy(
        tenant_id=current_user.tenant_id,
        created_by=current_user.id,
        conditions=payload.conditions.model_dump(),
        **payload.model_dump(exclude={"conditions"}),
    )
    db.add(policy)
    db.commit()
    db.refresh(policy)
    audit_service.create_event(
        db,
        tenant_id=current_user.tenant_id,
        actor_type=AuditActorType.USER,
        actor_id=current_user.id,
        event_type="policy.created",
        resource_type="policy",
        resource_id=policy.id,
        metadata={"severity": policy.severity.value, "decision": policy.decision.value},
    )
    db.commit()
    return PolicyResponse.model_validate(policy)


@router.put("/{policy_id}", response_model=PolicyResponse)
def update_policy(
    policy_id: str,
    payload: PolicyUpdate,
    current_user=Depends(require_roles(UserRole.OWNER, UserRole.ADMIN)),
    db: Session = Depends(get_db),
) -> PolicyResponse:
    policy = db.scalar(select(Policy).where(Policy.id == policy_id, Policy.tenant_id == current_user.tenant_id))
    if not policy:
        raise AppError("Policy not found.", status_code=404, code="policy_not_found")
    updates = payload.model_dump(exclude_unset=True)
    if "conditions" in updates and updates["conditions"] is not None:
        updates["conditions"] = payload.conditions.model_dump()
    for key, value in updates.items():
        setattr(policy, key, value)
    db.commit()
    db.refresh(policy)
    audit_service.create_event(
        db,
        tenant_id=current_user.tenant_id,
        actor_type=AuditActorType.USER,
        actor_id=current_user.id,
        event_type="policy.updated",
        resource_type="policy",
        resource_id=policy.id,
        metadata={"updated_fields": sorted(updates.keys())},
    )
    db.commit()
    return PolicyResponse.model_validate(policy)
