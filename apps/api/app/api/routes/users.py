from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.core.enums import UserRole
from app.db.session import get_db
from app.schemas.user import UserDeactivationRequest, UserResponse, UserUpdateRequest
from app.services.user_service import UserService

router = APIRouter()
user_service = UserService()


@router.get("", response_model=list[UserResponse])
def list_users(
    current_user=Depends(
        require_roles(
            UserRole.OWNER,
            UserRole.ADMIN,
            UserRole.SECURITY_REVIEWER,
        )
    ),
    db: Session = Depends(get_db),
) -> list[UserResponse]:
    return [
        UserResponse.model_validate(user)
        for user in user_service.list_users(db, tenant_id=current_user.tenant_id)
    ]


@router.get("/{user_id}", response_model=UserResponse)
def get_user(
    user_id: str,
    current_user=Depends(
        require_roles(
            UserRole.OWNER,
            UserRole.ADMIN,
            UserRole.SECURITY_REVIEWER,
        )
    ),
    db: Session = Depends(get_db),
) -> UserResponse:
    user = user_service.get_user(db, tenant_id=current_user.tenant_id, user_id=user_id)
    return UserResponse.model_validate(user)


@router.patch("/{user_id}", response_model=UserResponse)
def update_user(
    user_id: str,
    payload: UserUpdateRequest,
    request: Request,
    current_user=Depends(require_roles(UserRole.OWNER, UserRole.ADMIN)),
    db: Session = Depends(get_db),
) -> UserResponse:
    user = user_service.update_user(
        db,
        actor=current_user,
        user_id=user_id,
        payload=payload,
        ip_address=request.client.host if request.client else None,
    )
    return UserResponse.model_validate(user)


@router.post("/{user_id}/deactivate", response_model=UserResponse)
def deactivate_user(
    user_id: str,
    payload: UserDeactivationRequest,
    request: Request,
    current_user=Depends(require_roles(UserRole.OWNER, UserRole.ADMIN)),
    db: Session = Depends(get_db),
) -> UserResponse:
    user = user_service.deactivate_user(
        db,
        actor=current_user,
        user_id=user_id,
        payload=payload,
        ip_address=request.client.host if request.client else None,
    )
    return UserResponse.model_validate(user)


@router.post("/{user_id}/reactivate", response_model=UserResponse)
def reactivate_user(
    user_id: str,
    request: Request,
    current_user=Depends(require_roles(UserRole.OWNER, UserRole.ADMIN)),
    db: Session = Depends(get_db),
) -> UserResponse:
    user = user_service.reactivate_user(
        db,
        actor=current_user,
        user_id=user_id,
        ip_address=request.client.host if request.client else None,
    )
    return UserResponse.model_validate(user)
