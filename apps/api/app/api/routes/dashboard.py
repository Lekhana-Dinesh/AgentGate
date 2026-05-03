from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.schemas.dashboard import DashboardOverview
from app.services.dashboard_service import DashboardService

router = APIRouter()
dashboard_service = DashboardService()


@router.get("/overview", response_model=DashboardOverview)
def overview(current_user=Depends(get_current_user), db: Session = Depends(get_db)) -> DashboardOverview:
    return dashboard_service.overview(db, tenant_id=current_user.tenant_id)

