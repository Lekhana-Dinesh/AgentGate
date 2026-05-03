from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_gateway_principal
from app.core.enums import ToolCallStatus, UserRole
from app.core.errors import AppError
from app.db.session import get_db
from app.models import ToolCall
from app.schemas.gateway import GatewayDecisionResponse, ToolCallRequest, ToolCallResponse, serialize_tool_call
from app.services.gateway_service import GatewayService
from app.services.rate_limit_service import get_rate_limiter, get_rate_limit_settings

router = APIRouter()
gateway_service = GatewayService()


@router.post("/tool-call", response_model=GatewayDecisionResponse)
def tool_call(
    payload: ToolCallRequest,
    request: Request,
    principal=Depends(get_gateway_principal),
    db: Session = Depends(get_db),
) -> GatewayDecisionResponse:
    get_rate_limiter().enforce(
        scope="gateway",
        key_parts=[
            request.client.host if request.client else None,
            principal.tenant_id,
            principal.actor_id,
            principal.agent_id,
        ],
        settings=get_rate_limit_settings("gateway"),
        db=db,
        tenant_id=principal.tenant_id,
        actor_type=principal.actor_type,
        actor_id=principal.actor_id,
        ip_address=request.client.host if request.client else None,
        audit_on_exhaustion=True,
        resource_type="tenant",
        resource_id=principal.tenant_id,
        metadata={"endpoint": "gateway.tool-call"},
    )
    if principal.user and principal.role == UserRole.VIEWER:
        raise AppError(
            "Viewer accounts cannot invoke the gateway directly.",
            status_code=403,
            code="gateway_viewer_forbidden",
        )
    return gateway_service.process_tool_call(
        db,
        principal=principal,
        payload=payload,
        ip_address=request.client.host if request.client else None,
        request_id=getattr(request.state, "request_id", None),
    )


@router.get("/tool-calls", response_model=list[ToolCallResponse])
def list_tool_calls(
    status_filter: ToolCallStatus | None = Query(default=None, alias="status"),
    tool_name: str | None = None,
    agent_id: str | None = None,
    min_risk_score: float | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ToolCallResponse]:
    query = select(ToolCall).where(ToolCall.tenant_id == current_user.tenant_id)
    if status_filter:
        query = query.where(ToolCall.status == status_filter)
    if tool_name:
        query = query.where(ToolCall.tool_name == tool_name)
    if agent_id:
        query = query.where(ToolCall.agent_id == agent_id)
    if min_risk_score is not None:
        query = query.where(ToolCall.risk_score >= min_risk_score)
    tool_calls = list(db.scalars(query.order_by(ToolCall.created_at.desc()).offset(offset).limit(limit)))
    return [serialize_tool_call(item) for item in tool_calls]
