from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.core.enums import ApprovalStatus, AuditActorType, UserRole
from app.core.errors import AppError
from app.db.session import get_db
from app.models import ApprovalRequest, ToolCall
from app.schemas.approval import ApprovalDecisionRequest, ApprovalRequestResponse
from app.schemas.integration import ApprovalNotificationStatus
from app.schemas.gateway import serialize_tool_call
from app.services.approved_execution_service import ApprovedExecutionService
from app.services.approval_service import ApprovalService
from app.services.notification_service import NotificationService
from app.services.rate_limit_service import get_rate_limiter, get_rate_limit_settings

router = APIRouter()
approval_service = ApprovalService()
approved_execution_service = ApprovedExecutionService()
notification_service = NotificationService()


def _serialize_approval_response(
    *,
    approval: ApprovalRequest,
    tool_call: ToolCall | None,
    notification_status: ApprovalNotificationStatus | None,
    execution_requested: bool | None = None,
    db: Session,
) -> ApprovalRequestResponse:
    execute_now_requested = execution_requested
    if execute_now_requested is None:
        approval_payload = ((tool_call.response_payload or {}).get("approval") or {}) if tool_call else {}
        execute_now_requested = bool(approval_payload.get("execute_now"))

    return ApprovalRequestResponse(
        id=approval.id,
        tenant_id=approval.tenant_id,
        tool_call_id=approval.tool_call_id,
        requested_by_agent_id=approval.requested_by_agent_id,
        assigned_to_user_id=approval.assigned_to_user_id,
        status=approval.status,
        reason=approval.reason,
        approver_comment=approval.approver_comment,
        created_at=approval.created_at,
        decided_at=approval.decided_at,
        tool_call=serialize_tool_call(tool_call) if tool_call else None,
        notification_status=notification_status,
        execution_status=approved_execution_service.get_execution_status(
            db,
            tenant_id=approval.tenant_id,
            approval_id=approval.id,
            execute_now_requested=bool(execute_now_requested),
        ),
    )


@router.get("", response_model=list[ApprovalRequestResponse])
def list_approvals(
    status_filter: ApprovalStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    current_user=Depends(require_roles(UserRole.OWNER, UserRole.ADMIN, UserRole.SECURITY_REVIEWER, UserRole.APPROVER)),
    db: Session = Depends(get_db),
) -> list[ApprovalRequestResponse]:
    query = select(ApprovalRequest).where(ApprovalRequest.tenant_id == current_user.tenant_id)
    if status_filter:
        query = query.where(ApprovalRequest.status == status_filter)
    approvals = list(db.scalars(query.order_by(ApprovalRequest.created_at.desc()).offset(offset).limit(limit)))
    tool_call_ids = [item.tool_call_id for item in approvals]
    notification_statuses = notification_service.map_notification_statuses(
        db,
        tenant_id=current_user.tenant_id,
        approval_ids=[item.id for item in approvals],
    )
    execution_statuses = approved_execution_service.map_execution_statuses(
        db,
        tenant_id=current_user.tenant_id,
        approval_ids=[item.id for item in approvals],
    )
    tool_calls = {}
    if tool_call_ids:
        tool_calls = {
            call.id: call
            for call in db.scalars(
                select(ToolCall).where(
                    ToolCall.id.in_(tool_call_ids),
                    ToolCall.tenant_id == current_user.tenant_id,
                )
            )
        }
    return [
        ApprovalRequestResponse(
            id=item.id,
            tenant_id=item.tenant_id,
            tool_call_id=item.tool_call_id,
            requested_by_agent_id=item.requested_by_agent_id,
            assigned_to_user_id=item.assigned_to_user_id,
            status=item.status,
            reason=item.reason,
            approver_comment=item.approver_comment,
            created_at=item.created_at,
            decided_at=item.decided_at,
            tool_call=serialize_tool_call(tool_calls[item.tool_call_id]) if item.tool_call_id in tool_calls else None,
            notification_status=notification_statuses.get(item.id),
            execution_status=execution_statuses.get(item.id),
        )
        for item in approvals
    ]


@router.post("/{approval_id}/approve", response_model=ApprovalRequestResponse)
def approve_request(
    approval_id: str,
    payload: ApprovalDecisionRequest,
    request: Request,
    current_user=Depends(require_roles(UserRole.OWNER, UserRole.ADMIN, UserRole.SECURITY_REVIEWER, UserRole.APPROVER)),
    db: Session = Depends(get_db),
) -> ApprovalRequestResponse:
    get_rate_limiter().enforce(
        scope="approval",
        key_parts=[
            request.client.host if request.client else None,
            current_user.tenant_id,
            current_user.id,
        ],
        settings=get_rate_limit_settings("approval"),
        db=db,
        tenant_id=current_user.tenant_id,
        actor_type=AuditActorType.USER,
        actor_id=current_user.id,
        ip_address=request.client.host if request.client else None,
        audit_on_exhaustion=True,
        resource_type="approval_request",
        resource_id=approval_id,
        metadata={"decision": "approve"},
    )
    approval = approval_service.decide(
        db,
        approval_id=approval_id,
        tenant_id=current_user.tenant_id,
        approver=current_user,
        approve=True,
        payload=payload,
        ip_address=request.client.host if request.client else None,
    )
    tool_call = db.scalar(
        select(ToolCall).where(
            ToolCall.id == approval.tool_call_id,
            ToolCall.tenant_id == current_user.tenant_id,
        )
    )
    return _serialize_approval_response(
        approval=approval,
        tool_call=tool_call,
        notification_status=notification_service.get_approval_notification_status(
            db,
            tenant_id=current_user.tenant_id,
            approval_id=approval.id,
        ),
        execution_requested=payload.execute_now,
        db=db,
    )


@router.post("/{approval_id}/reject", response_model=ApprovalRequestResponse)
def reject_request(
    approval_id: str,
    payload: ApprovalDecisionRequest,
    request: Request,
    current_user=Depends(require_roles(UserRole.OWNER, UserRole.ADMIN, UserRole.SECURITY_REVIEWER, UserRole.APPROVER)),
    db: Session = Depends(get_db),
) -> ApprovalRequestResponse:
    get_rate_limiter().enforce(
        scope="approval",
        key_parts=[
            request.client.host if request.client else None,
            current_user.tenant_id,
            current_user.id,
        ],
        settings=get_rate_limit_settings("approval"),
        db=db,
        tenant_id=current_user.tenant_id,
        actor_type=AuditActorType.USER,
        actor_id=current_user.id,
        ip_address=request.client.host if request.client else None,
        audit_on_exhaustion=True,
        resource_type="approval_request",
        resource_id=approval_id,
        metadata={"decision": "reject"},
    )
    approval = approval_service.decide(
        db,
        approval_id=approval_id,
        tenant_id=current_user.tenant_id,
        approver=current_user,
        approve=False,
        payload=payload,
        ip_address=request.client.host if request.client else None,
    )
    tool_call = db.scalar(
        select(ToolCall).where(
            ToolCall.id == approval.tool_call_id,
            ToolCall.tenant_id == current_user.tenant_id,
        )
    )
    return _serialize_approval_response(
        approval=approval,
        tool_call=tool_call,
        notification_status=notification_service.get_approval_notification_status(
            db,
            tenant_id=current_user.tenant_id,
            approval_id=approval.id,
        ),
        execution_requested=False,
        db=db,
    )


@router.get("/{approval_id}/notification-status", response_model=ApprovalNotificationStatus)
def get_approval_notification_status(
    approval_id: str,
    current_user=Depends(require_roles(UserRole.OWNER, UserRole.ADMIN, UserRole.SECURITY_REVIEWER, UserRole.APPROVER)),
    db: Session = Depends(get_db),
) -> ApprovalNotificationStatus:
    approval = db.scalar(
        select(ApprovalRequest).where(
            ApprovalRequest.id == approval_id,
            ApprovalRequest.tenant_id == current_user.tenant_id,
        )
    )
    if not approval:
        raise AppError("Approval request not found.", status_code=404, code="approval_not_found")
    return notification_service.get_approval_notification_status(
        db,
        tenant_id=current_user.tenant_id,
        approval_id=approval_id,
    )
