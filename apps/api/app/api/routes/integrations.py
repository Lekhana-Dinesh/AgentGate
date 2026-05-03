from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.deps import require_roles
from app.core.enums import UserRole
from app.schemas.integration import SlackIntegrationHealthResponse
from app.services.notification_service import NotificationService

router = APIRouter()
notification_service = NotificationService()


@router.get("/slack/health", response_model=SlackIntegrationHealthResponse)
def get_slack_health(
    probe: bool = Query(default=False),
    _: object = Depends(
        require_roles(
            UserRole.OWNER,
            UserRole.ADMIN,
            UserRole.SECURITY_REVIEWER,
            UserRole.DEVELOPER,
        )
    ),
) -> SlackIntegrationHealthResponse:
    return notification_service.slack_health(probe=probe)
