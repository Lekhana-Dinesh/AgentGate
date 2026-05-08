from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.core.enums import UserRole
from app.db.session import get_db
from app.schemas.onboarding import OnboardingActionResponse, OnboardingStatusResponse
from app.services.onboarding_service import OnboardingService

router = APIRouter()
onboarding_service = OnboardingService()


@router.get("/status", response_model=OnboardingStatusResponse)
def get_onboarding_status(
    current_user=Depends(require_roles(UserRole.OWNER, UserRole.ADMIN, UserRole.SECURITY_REVIEWER)),
    db: Session = Depends(get_db),
) -> OnboardingStatusResponse:
    return onboarding_service.get_status(db, tenant_id=current_user.tenant_id)


@router.post("/dismiss", response_model=OnboardingActionResponse)
def dismiss_onboarding(
    request: Request,
    current_user=Depends(require_roles(UserRole.OWNER, UserRole.ADMIN)),
    db: Session = Depends(get_db),
) -> OnboardingActionResponse:
    return onboarding_service.dismiss(
        db,
        tenant_id=current_user.tenant_id,
        actor_id=current_user.id,
        ip_address=request.client.host if request.client else None,
    )


@router.post("/reset", response_model=OnboardingActionResponse)
def reset_onboarding(
    request: Request,
    current_user=Depends(require_roles(UserRole.OWNER, UserRole.ADMIN)),
    db: Session = Depends(get_db),
) -> OnboardingActionResponse:
    return onboarding_service.reset(
        db,
        tenant_id=current_user.tenant_id,
        actor_id=current_user.id,
        ip_address=request.client.host if request.client else None,
    )


@router.post("/demo-policy", response_model=OnboardingActionResponse)
def create_demo_policy(
    request: Request,
    current_user=Depends(require_roles(UserRole.OWNER, UserRole.ADMIN)),
    db: Session = Depends(get_db),
) -> OnboardingActionResponse:
    return onboarding_service.create_demo_policy(
        db,
        tenant_id=current_user.tenant_id,
        actor_id=current_user.id,
        ip_address=request.client.host if request.client else None,
    )
