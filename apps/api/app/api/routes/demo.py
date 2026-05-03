from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import Principal, require_roles
from app.core.enums import AuditActorType, UserRole
from app.db.session import get_db
from app.services.demo_service import DemoService

router = APIRouter()
demo_service = DemoService()


@router.post("/run-sales-agent-risk-scenario")
def run_demo(
    current_user=Depends(
        require_roles(UserRole.OWNER, UserRole.ADMIN, UserRole.DEVELOPER, UserRole.SECURITY_REVIEWER)
    ),
    db: Session = Depends(get_db),
) -> dict:
    return demo_service.run_sales_agent_scenario(
        db,
        principal=Principal(
            tenant_id=current_user.tenant_id,
            actor_type=AuditActorType.USER,
            actor_id=current_user.id,
            role=current_user.role,
            user=current_user,
        ),
    )
