from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.core.enums import UserRole
from app.db.session import get_db
from app.schemas.settings import SettingsOverviewResponse
from app.services.settings_service import SettingsService

router = APIRouter()
settings_service = SettingsService()


@router.get("/overview", response_model=SettingsOverviewResponse)
def get_settings_overview(
    current_user=Depends(
        require_roles(
            UserRole.OWNER,
            UserRole.ADMIN,
            UserRole.SECURITY_REVIEWER,
        )
    ),
    db: Session = Depends(get_db),
) -> SettingsOverviewResponse:
    return settings_service.get_overview(db, tenant_id=current_user.tenant_id)
