from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.enums import TraceStatus, TraceStepType
from app.core.errors import AppError
from app.models import ExecutionTrace, TraceStep
from app.models.base import utcnow
from app.services.payload_service import PayloadService


class TraceService:
    def __init__(self, payload_service: PayloadService | None = None) -> None:
        self.payload_service = payload_service or PayloadService()

    def create_trace(
        self,
        db: Session,
        *,
        tenant_id: str,
        agent_id: str,
        user_id: str | None,
        original_intent: str,
        metadata: dict | None = None,
    ) -> ExecutionTrace:
        trace = ExecutionTrace(
            tenant_id=tenant_id,
            agent_id=agent_id,
            user_id=user_id,
            original_intent=original_intent,
            status=TraceStatus.RUNNING,
            summary="",
            metadata_json=self.payload_service.sanitize_payload(metadata or {}),
        )
        db.add(trace)
        db.flush()
        return trace

    def ensure_trace(
        self,
        db: Session,
        *,
        trace_id: str | None,
        tenant_id: str,
        agent_id: str,
        user_id: str | None,
        original_intent: str,
        metadata: dict | None = None,
    ) -> ExecutionTrace:
        if trace_id:
            trace = db.scalar(
                select(ExecutionTrace).where(
                    ExecutionTrace.id == trace_id,
                    ExecutionTrace.tenant_id == tenant_id,
                ).with_for_update().execution_options(populate_existing=True)
            )
            if not trace:
                raise AppError("Trace not found in tenant.", status_code=404, code="trace_not_found")
            if trace.agent_id != agent_id:
                raise AppError(
                    "Trace does not belong to the specified agent.",
                    status_code=409,
                    code="trace_agent_mismatch",
                )
            if trace.user_id and user_id and trace.user_id != user_id:
                raise AppError(
                    "Trace does not belong to the specified user context.",
                    status_code=409,
                    code="trace_user_mismatch",
                )
            if trace.original_intent != original_intent:
                raise AppError(
                    "Trace intent does not match the current tool-call request.",
                    status_code=409,
                    code="trace_intent_mismatch",
                )
            if trace.status == TraceStatus.PENDING_APPROVAL:
                raise AppError(
                    "Trace is paused pending approval and cannot accept new steps yet.",
                    status_code=409,
                    code="trace_pending_approval",
                )
            if trace.status in {TraceStatus.COMPLETED, TraceStatus.BLOCKED, TraceStatus.FAILED}:
                raise AppError(
                    "Trace is already closed and cannot accept new steps.",
                    status_code=409,
                    code="trace_closed",
                )
            return trace
        return self.create_trace(
            db,
            tenant_id=tenant_id,
            agent_id=agent_id,
            user_id=user_id,
            original_intent=original_intent,
            metadata=metadata,
        )

    def append_step(
        self,
        db: Session,
        *,
        trace_id: str,
        type: TraceStepType,
        content: str,
        metadata: dict | None = None,
    ) -> TraceStep:
        # Hold the parent row through commit before allocating the next step number.
        db.scalar(select(ExecutionTrace.id).where(ExecutionTrace.id == trace_id).with_for_update())
        next_step = (db.scalar(select(func.max(TraceStep.step_number)).where(TraceStep.trace_id == trace_id)) or 0) + 1
        step = TraceStep(
            trace_id=trace_id,
            step_number=next_step,
            type=type,
            content=content,
            metadata_json=self.payload_service.sanitize_payload(metadata or {}),
        )
        db.add(step)
        db.flush()
        return step

    def set_status(
        self,
        db: Session,
        *,
        trace_id: str,
        status: TraceStatus,
        summary: str,
        completed: bool = False,
    ) -> None:
        trace = db.scalar(select(ExecutionTrace).where(ExecutionTrace.id == trace_id))
        if not trace:
            raise AppError("Trace not found.", status_code=404, code="trace_not_found")
        trace.status = status
        trace.summary = summary
        if completed:
            trace.completed_at = utcnow()
        db.flush()

    def get_trace(
        self, db: Session, *, trace_id: str, tenant_id: str, for_update: bool = False,
    ) -> ExecutionTrace:
        query = select(ExecutionTrace).where(
            ExecutionTrace.id == trace_id,
            ExecutionTrace.tenant_id == tenant_id,
        )
        if for_update:
            query = query.with_for_update().execution_options(populate_existing=True)
        trace = db.scalar(query)
        if not trace:
            raise AppError("Trace not found.", status_code=404, code="trace_not_found")
        return trace

    def list_steps(self, db: Session, *, trace_id: str) -> list[TraceStep]:
        return list(
            db.scalars(
                select(TraceStep).where(TraceStep.trace_id == trace_id).order_by(TraceStep.step_number.asc())
            )
        )
