from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import AuditActorType, JobStatus, JobType, ToolCallStatus, TraceStatus, TraceStepType
from app.core.errors import AppError
from app.core.retention import PAYLOAD_REDACTION_STATUS_PURGED, is_purged_execution_payload
from app.models import ApprovalRequest, Job, Tool, ToolCall, User
from app.schemas.job import ApprovalExecutionStatus, serialize_job_summary
from app.services.audit_service import AuditService
from app.services.job_service import JobService, JobProcessingError
from app.services.payload_service import PayloadService
from app.services.tool_executor import ToolExecutor
from app.services.trace_service import TraceService

APPROVAL_EXECUTION_QUEUED_EVENT = "approval.execution.queued"
APPROVAL_EXECUTION_SUCCEEDED_EVENT = "approval.execution.succeeded"
APPROVAL_EXECUTION_FAILED_EVENT = "approval.execution.failed"


class ApprovedExecutionService:
    def __init__(self) -> None:
        self.audit_service = AuditService()
        self.job_service = JobService()
        self.payload_service = PayloadService()
        self.tool_executor = ToolExecutor()
        self.trace_service = TraceService()

    def job_idempotency_key(self, approval_id: str) -> str:
        return f"approval_execution.tool_call:{approval_id}"

    def enqueue_approved_execution(
        self,
        db: Session,
        *,
        approval: ApprovalRequest,
        tool_call: ToolCall,
        approver: User,
        ip_address: str | None,
    ) -> Job:
        tool = db.scalar(select(Tool).where(Tool.tenant_id == approval.tenant_id, Tool.name == tool_call.tool_name))
        if not tool:
            raise AppError("Tool not found for approval execution.", status_code=404, code="tool_not_found")
        if not self.tool_executor.supports(
            tool_call.tool_name,
            tool_call.action_name,
            {},
            tool_type=tool.type.value,
            base_url=tool.base_url,
            config=tool.config or {},
        ):
            raise AppError(
                "Immediate execution is not supported for this tool in the current build.",
                status_code=400,
                code="tool_execution_unsupported",
            )

        job = self.job_service.enqueue(
            db,
            tenant_id=approval.tenant_id,
            job_type=JobType.APPROVAL_EXECUTION_TOOL_CALL,
            idempotency_key=self.job_idempotency_key(approval.id),
            payload={
                "approval_id": approval.id,
                "tool_call_id": tool_call.id,
                "approver_id": approver.id,
                "ip_address": ip_address,
            },
            max_attempts=1,
        )
        self.audit_service.create_event(
            db,
            tenant_id=approval.tenant_id,
            actor_type=AuditActorType.USER,
            actor_id=approver.id,
            event_type=APPROVAL_EXECUTION_QUEUED_EVENT,
            resource_type="tool_call",
            resource_id=tool_call.id,
            metadata={"approval_id": approval.id, "job_id": job.id},
            ip_address=ip_address,
        )
        tool_call.response_payload = {
            **(tool_call.response_payload or {}),
            "approved_execution_requested": True,
            "approved_execution_job_id": job.id,
        }
        return job

    def handle_tool_call_execution_job(self, db: Session, *, job: Job) -> None:
        approval_id = str(job.payload.get("approval_id") or "").strip()
        tool_call_id = str(job.payload.get("tool_call_id") or "").strip()
        approver_id = str(job.payload.get("approver_id") or "").strip() or None
        ip_address = str(job.payload.get("ip_address") or "").strip() or None
        if not approval_id or not tool_call_id:
            raise JobProcessingError(
                detail="Approved execution job payload is invalid.",
                code="approval_execution_job_invalid",
                retryable=False,
            )

        approval = db.scalar(
            select(ApprovalRequest).where(
                ApprovalRequest.id == approval_id,
                ApprovalRequest.tenant_id == job.tenant_id,
            )
        )
        tool_call = db.scalar(
            select(ToolCall).where(
                ToolCall.id == tool_call_id,
                ToolCall.tenant_id == job.tenant_id,
            )
        )
        if not approval or not tool_call:
            raise JobProcessingError(
                detail="Approved execution target was not found in the tenant.",
                code="approval_execution_target_not_found",
                retryable=False,
            )
        if approval.status.value != "approved":
            raise JobProcessingError(
                detail="Approval is not in an approved state for execution.",
                code="approval_not_ready_for_execution",
                retryable=False,
            )
        if tool_call.status == ToolCallStatus.EXECUTED:
            return

        approver = None
        if approver_id:
            approver = db.scalar(
                select(User).where(
                    User.id == approver_id,
                    User.tenant_id == job.tenant_id,
                )
            )

        trace_id = tool_call.trace_id or tool_call.request_payload.get("trace_id")
        trace_finalize = bool((tool_call.request_payload.get("metadata") or {}).get("trace_finalize"))

        try:
            tool = db.scalar(
                select(Tool).where(
                    Tool.tenant_id == job.tenant_id,
                    Tool.name == tool_call.tool_name,
                )
            )
            if not tool:
                raise AppError("Tool not found for approval execution.", status_code=404, code="tool_not_found")

            execution_payload = tool_call.request_payload.get(
                "execution_arguments",
                tool_call.request_payload.get("arguments", {}),
            )
            if tool_call.payload_redaction_status == PAYLOAD_REDACTION_STATUS_PURGED or is_purged_execution_payload(
                execution_payload
            ):
                raise AppError(
                    "Protected execution payload has already been purged by retention policy.",
                    status_code=409,
                    code="protected_payload_purged",
                )
            execution_arguments = self.payload_service.decrypt_payload_for_execution(
                execution_payload
            )
            if not self.tool_executor.supports(
                tool_call.tool_name,
                tool_call.action_name,
                execution_arguments,
                tool_type=tool.type.value,
                base_url=tool.base_url,
                config=tool.config or {},
            ):
                raise AppError(
                    "Immediate execution is not supported for this tool in the current build.",
                    status_code=400,
                    code="tool_execution_unsupported",
                )

            output = self.tool_executor.execute(
                tool_call.tool_name,
                tool_call.action_name,
                execution_arguments,
                tool_type=tool.type.value,
                base_url=tool.base_url,
                config=tool.config or {},
            )
            sanitized_output = self.payload_service.sanitize_payload(output)
            tool_call.status = ToolCallStatus.EXECUTED
            tool_call.response_payload = {
                **(tool_call.response_payload or {}),
                "tool_output": sanitized_output,
                "approved_execution": True,
                "approved_execution_job_id": job.id,
            }

            if trace_id:
                approver_label = approver.email if approver else (approver_id or "an approved reviewer")
                self.trace_service.append_step(
                    db,
                    trace_id=trace_id,
                    type=TraceStepType.TOOL_CALL,
                    content=(
                        f"Approved execution completed for {tool_call.tool_name}.{tool_call.action_name} "
                        f"after review by {approver_label}."
                    ),
                    metadata={"tool_output": sanitized_output, "approval_id": approval.id, "job_id": job.id},
                )
                if trace_finalize:
                    self.trace_service.set_status(
                        db,
                        trace_id=trace_id,
                        status=TraceStatus.COMPLETED,
                        summary=(
                            f"Approval granted and execution completed for "
                            f"{tool_call.tool_name}.{tool_call.action_name}."
                        ),
                        completed=True,
                    )
                    self.trace_service.append_step(
                        db,
                        trace_id=trace_id,
                        type=TraceStepType.FINAL,
                        content="Approved execution completed successfully.",
                        metadata={"approval_id": approval.id, "tool_call_id": tool_call.id, "job_id": job.id},
                    )
                else:
                    self.trace_service.set_status(
                        db,
                        trace_id=trace_id,
                        status=TraceStatus.RUNNING,
                        summary="Approval granted and tool execution completed for this step.",
                    )

            self.audit_service.create_event(
                db,
                tenant_id=job.tenant_id,
                actor_type=AuditActorType.SYSTEM,
                actor_id=None,
                event_type=APPROVAL_EXECUTION_SUCCEEDED_EVENT,
                resource_type="tool_call",
                resource_id=tool_call.id,
                metadata={"approval_id": approval.id, "job_id": job.id},
                ip_address=ip_address,
            )
        except AppError as exc:
            self._record_execution_failure(
                db,
                approval=approval,
                tool_call=tool_call,
                job=job,
                trace_id=trace_id,
                ip_address=ip_address,
            )
            raise JobProcessingError(
                detail=exc.detail,
                code=exc.code,
                retryable=False,
                persist_state=True,
            ) from exc
        except Exception as exc:  # pragma: no cover - fail-closed safeguard
            self._record_execution_failure(
                db,
                approval=approval,
                tool_call=tool_call,
                job=job,
                trace_id=trace_id,
                ip_address=ip_address,
            )
            raise JobProcessingError(
                detail="Approved execution failed unexpectedly.",
                code="approved_execution_failed",
                retryable=False,
                persist_state=True,
            ) from exc

    def get_execution_status(
        self,
        db: Session,
        *,
        tenant_id: str,
        approval_id: str,
        execute_now_requested: bool,
    ) -> ApprovalExecutionStatus | None:
        if not execute_now_requested:
            return ApprovalExecutionStatus(status="not_requested", message="Approved execution was not requested.")

        job = db.scalar(
            select(Job).where(
                Job.tenant_id == tenant_id,
                Job.idempotency_key == self.job_idempotency_key(approval_id),
            )
        )
        if not job:
            return ApprovalExecutionStatus(status="not_requested")
        message = job.last_error
        if job.status == JobStatus.SUCCEEDED:
            message = "Approved execution completed successfully."
        return ApprovalExecutionStatus(
            status=job.status.value,
            job=serialize_job_summary(job),
            message=message,
        )

    def map_execution_statuses(
        self,
        db: Session,
        *,
        tenant_id: str,
        approval_ids: list[str],
    ) -> dict[str, ApprovalExecutionStatus]:
        if not approval_ids:
            return {}
        keys = [self.job_idempotency_key(item) for item in approval_ids]
        jobs = list(
            db.scalars(
                select(Job).where(
                    Job.tenant_id == tenant_id,
                    Job.idempotency_key.in_(keys),
                )
            )
        )
        by_key = {job.idempotency_key: job for job in jobs}
        statuses: dict[str, ApprovalExecutionStatus] = {}
        for approval_id in approval_ids:
            job = by_key.get(self.job_idempotency_key(approval_id))
            if not job:
                continue
            statuses[approval_id] = ApprovalExecutionStatus(
                status=job.status.value,
                job=serialize_job_summary(job),
                message=(
                    "Approved execution completed successfully."
                    if job.status == JobStatus.SUCCEEDED
                    else job.last_error
                ),
            )
        return statuses

    def _record_execution_failure(
        self,
        db: Session,
        *,
        approval: ApprovalRequest,
        tool_call: ToolCall,
        job: Job,
        trace_id: str | None,
        ip_address: str | None,
    ) -> None:
        tool_call.status = ToolCallStatus.FAILED
        tool_call.response_payload = {
            **(tool_call.response_payload or {}),
            "approved_execution": False,
            "approved_execution_job_id": job.id,
            "execution_error": {
                "tool_name": tool_call.tool_name,
                "action_name": tool_call.action_name,
            },
        }
        if trace_id:
            self.trace_service.append_step(
                db,
                trace_id=trace_id,
                type=TraceStepType.ERROR,
                content="Approved execution failed during tool dispatch.",
                metadata={"approval_id": approval.id, "tool_call_id": tool_call.id, "job_id": job.id},
            )
            self.trace_service.set_status(
                db,
                trace_id=trace_id,
                status=TraceStatus.FAILED,
                summary="Approval granted, but tool execution failed.",
                completed=True,
            )
        self.audit_service.create_event(
            db,
            tenant_id=approval.tenant_id,
            actor_type=AuditActorType.SYSTEM,
            actor_id=None,
            event_type=APPROVAL_EXECUTION_FAILED_EVENT,
            resource_type="tool_call",
            resource_id=tool_call.id,
            metadata={"approval_id": approval.id, "job_id": job.id},
            ip_address=ip_address,
        )
