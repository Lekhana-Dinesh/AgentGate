from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import ApprovalStatus, AuditActorType, ToolCallStatus, TraceStatus, TraceStepType
from app.core.errors import AppError
from app.core.metrics import get_metrics_registry
from app.models import ApprovalRequest, ToolCall, User
from app.models.base import utcnow
from app.schemas.approval import ApprovalDecisionRequest
from app.services.approved_execution_service import ApprovedExecutionService
from app.services.audit_service import AuditService
from app.services.trace_service import TraceService


class ApprovalService:
    def __init__(self) -> None:
        self.audit_service = AuditService()
        self.approved_execution_service = ApprovedExecutionService()
        self.trace_service = TraceService()
        self.metrics = get_metrics_registry()

    def decide(
        self,
        db: Session,
        *,
        approval_id: str,
        tenant_id: str,
        approver: User,
        approve: bool,
        payload: ApprovalDecisionRequest,
        ip_address: str | None = None,
    ) -> ApprovalRequest:
        approval = db.scalar(
            select(ApprovalRequest).where(
                ApprovalRequest.id == approval_id,
                ApprovalRequest.tenant_id == tenant_id,
            )
        )
        if not approval:
            raise AppError("Approval request not found.", status_code=404, code="approval_not_found")
        if approval.status != ApprovalStatus.PENDING:
            raise AppError("Approval request is already decided.", status_code=409, code="approval_closed")

        tool_call = db.scalar(
            select(ToolCall).where(
                ToolCall.id == approval.tool_call_id,
                ToolCall.tenant_id == tenant_id,
            )
        )
        if not tool_call:
            raise AppError("Tool call not found.", status_code=404, code="tool_call_not_found")

        trace_id = tool_call.trace_id or tool_call.request_payload.get("trace_id")
        approval.assigned_to_user_id = approver.id
        approval.approver_comment = payload.approver_comment
        approval.decided_at = utcnow()
        execution_job = None

        if approve:
            approval.status = ApprovalStatus.APPROVED
            tool_call.status = ToolCallStatus.ALLOWED
            tool_call.response_payload = {
                **(tool_call.response_payload or {}),
                "approval": {
                    "status": approval.status.value,
                    "approver_id": approver.id,
                    "approver_comment": payload.approver_comment,
                    "execute_now": payload.execute_now,
                    "decided_at": approval.decided_at.isoformat(),
                },
            }

            if payload.execute_now:
                execution_job = self.approved_execution_service.enqueue_approved_execution(
                    db,
                    approval=approval,
                    tool_call=tool_call,
                    approver=approver,
                    ip_address=ip_address,
                )
                if trace_id:
                    self.trace_service.append_step(
                        db,
                        trace_id=trace_id,
                        type=TraceStepType.APPROVAL,
                        content=f"Approval approved by {approver.email}. Approved execution queued.",
                        metadata={
                            "approval_id": approval.id,
                            "comment": payload.approver_comment,
                            "job_id": execution_job.id,
                        },
                    )
                    self.trace_service.set_status(
                        db,
                        trace_id=trace_id,
                        status=TraceStatus.RUNNING,
                        summary="Approval granted. Approved execution is queued.",
                    )
            elif trace_id:
                self.trace_service.append_step(
                    db,
                    trace_id=trace_id,
                    type=TraceStepType.APPROVAL,
                    content=f"Approval approved by {approver.email}.",
                    metadata={"approval_id": approval.id, "comment": payload.approver_comment},
                )
                self.trace_service.set_status(
                    db,
                    trace_id=trace_id,
                    status=TraceStatus.RUNNING,
                    summary="Approval granted. Waiting for the caller to resume execution.",
                )
        else:
            if not payload.approver_comment:
                raise AppError(
                    "Approver comment is required when rejecting a request.",
                    status_code=422,
                    code="approver_comment_required",
                )
            approval.status = ApprovalStatus.REJECTED
            tool_call.status = ToolCallStatus.BLOCKED
            tool_call.decision_reason = f"{tool_call.decision_reason}; Rejected by approver."
            tool_call.response_payload = {
                **(tool_call.response_payload or {}),
                "approval": {
                    "status": approval.status.value,
                    "approver_id": approver.id,
                    "approver_comment": payload.approver_comment,
                    "execute_now": False,
                    "decided_at": approval.decided_at.isoformat(),
                },
            }
            if trace_id:
                self.trace_service.append_step(
                    db,
                    trace_id=trace_id,
                    type=TraceStepType.APPROVAL,
                    content=f"Approval rejected by {approver.email}.",
                    metadata={"approval_id": approval.id, "comment": payload.approver_comment},
                )
                self.trace_service.set_status(
                    db,
                    trace_id=trace_id,
                    status=TraceStatus.BLOCKED,
                    summary="Approval rejected.",
                    completed=True,
                )
                self.trace_service.append_step(
                    db,
                    trace_id=trace_id,
                    type=TraceStepType.FINAL,
                    content="Execution ended because the approval request was rejected.",
                    metadata={"approval_id": approval.id, "tool_call_id": tool_call.id},
                )

        self.audit_service.create_event(
            db,
            tenant_id=tenant_id,
            actor_type=AuditActorType.USER,
            actor_id=approver.id,
            event_type=f"approval.{approval.status.value}",
            resource_type="approval_request",
            resource_id=approval.id,
            metadata={
                "tool_call_id": tool_call.id,
                "execute_now": payload.execute_now,
                "approved": approve,
                "execution_job_id": execution_job.id if execution_job else None,
            },
            ip_address=ip_address,
        )
        self.metrics.increment("agentgate_approvals_total", status=approval.status.value)

        db.commit()
        if execution_job is not None:
            self.approved_execution_service.job_service.dispatch_after_commit(
                db,
                job_id=execution_job.id,
                raise_on_error=True,
            )
        db.refresh(approval)
        return approval
