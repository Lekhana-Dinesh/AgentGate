from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.core.enums import AuditActorType, TraceStatus, UserRole
from app.core.errors import AppError
from app.db.session import get_db
from app.models import Agent, ExecutionTrace, User
from app.schemas.trace import TraceCreate, TraceResponse, TraceStepCreate, TraceStepResponse
from app.services.audit_service import AuditService
from app.services.payload_service import PayloadService
from app.services.trace_service import TraceService

router = APIRouter()
trace_service = TraceService()
audit_service = AuditService()
payload_service = PayloadService()


@router.get("", response_model=list[TraceResponse])
def list_traces(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[TraceResponse]:
    traces = list(
        db.scalars(
            select(ExecutionTrace)
            .where(ExecutionTrace.tenant_id == current_user.tenant_id)
            .order_by(ExecutionTrace.started_at.desc())
            .offset(offset)
            .limit(limit)
        )
    )
    return [
        TraceResponse(
            id=trace.id,
            tenant_id=trace.tenant_id,
            agent_id=trace.agent_id,
            user_id=trace.user_id,
            original_intent=trace.original_intent,
            status=trace.status,
            started_at=trace.started_at,
            completed_at=trace.completed_at,
            summary=trace.summary,
            metadata_json=payload_service.sanitize_payload(trace.metadata_json),
            steps=[],
        )
        for trace in traces
    ]


@router.post("", response_model=TraceResponse, status_code=status.HTTP_201_CREATED)
def create_trace(
    payload: TraceCreate,
    current_user=Depends(require_roles(UserRole.OWNER, UserRole.ADMIN, UserRole.DEVELOPER, UserRole.SECURITY_REVIEWER)),
    db: Session = Depends(get_db),
) -> TraceResponse:
    agent = db.scalar(
        select(Agent).where(Agent.id == payload.agent_id, Agent.tenant_id == current_user.tenant_id)
    )
    if not agent:
        raise AppError("Agent not found.", status_code=404, code="agent_not_found")
    if payload.user_id and payload.user_id != current_user.id and current_user.role not in {
        UserRole.OWNER,
        UserRole.ADMIN,
    }:
        raise AppError(
            "Only owners and admins can create traces for another user context.",
            status_code=403,
            code="trace_user_context_forbidden",
        )
    if payload.user_id:
        trace_user = db.scalar(
            select(User).where(User.id == payload.user_id, User.tenant_id == current_user.tenant_id)
        )
        if not trace_user:
            raise AppError("Trace user not found.", status_code=404, code="trace_user_not_found")
        if not trace_user.is_active:
            raise AppError("Trace user is inactive.", status_code=403, code="inactive_user")
    trace = trace_service.create_trace(
        db,
        tenant_id=current_user.tenant_id,
        agent_id=payload.agent_id,
        user_id=payload.user_id or current_user.id,
        original_intent=payload.original_intent,
        metadata=payload.metadata,
    )
    db.commit()
    db.refresh(trace)
    audit_service.create_event(
        db,
        tenant_id=current_user.tenant_id,
        actor_type=AuditActorType.USER,
        actor_id=current_user.id,
        event_type="trace.created",
        resource_type="execution_trace",
        resource_id=trace.id,
        metadata={"agent_id": trace.agent_id},
    )
    db.commit()
    return TraceResponse(
        id=trace.id,
        tenant_id=trace.tenant_id,
        agent_id=trace.agent_id,
        user_id=trace.user_id,
        original_intent=trace.original_intent,
        status=trace.status,
        started_at=trace.started_at,
        completed_at=trace.completed_at,
        summary=trace.summary,
        metadata_json=payload_service.sanitize_payload(trace.metadata_json),
        steps=[],
    )


@router.post("/{trace_id}/steps", response_model=TraceStepResponse, status_code=status.HTTP_201_CREATED)
def append_trace_step(
    trace_id: str,
    payload: TraceStepCreate,
    current_user=Depends(require_roles(UserRole.OWNER, UserRole.ADMIN, UserRole.DEVELOPER, UserRole.SECURITY_REVIEWER)),
    db: Session = Depends(get_db),
) -> TraceStepResponse:
    trace = trace_service.get_trace(db, trace_id=trace_id, tenant_id=current_user.tenant_id, for_update=True)
    if trace.status in {TraceStatus.COMPLETED, TraceStatus.BLOCKED, TraceStatus.FAILED}:
        raise AppError(
            "Closed traces cannot accept new steps.",
            status_code=409,
            code="trace_closed",
        )
    step = trace_service.append_step(
        db,
        trace_id=trace_id,
        type=payload.type,
        content=payload.content,
        metadata=payload.metadata,
    )
    db.commit()
    audit_service.create_event(
        db,
        tenant_id=current_user.tenant_id,
        actor_type=AuditActorType.USER,
        actor_id=current_user.id,
        event_type="trace.step.appended",
        resource_type="trace_step",
        resource_id=step.id,
        metadata={"trace_id": trace_id, "step_type": step.type.value},
    )
    db.commit()
    return TraceStepResponse(
        id=step.id,
        trace_id=step.trace_id,
        step_number=step.step_number,
        type=step.type,
        content=step.content,
        metadata_json=payload_service.sanitize_payload(step.metadata_json),
        created_at=step.created_at,
    )


@router.get("/{trace_id}", response_model=TraceResponse)
def get_trace(trace_id: str, current_user=Depends(get_current_user), db: Session = Depends(get_db)) -> TraceResponse:
    trace = trace_service.get_trace(db, trace_id=trace_id, tenant_id=current_user.tenant_id)
    steps = trace_service.list_steps(db, trace_id=trace_id)
    return TraceResponse(
        id=trace.id,
        tenant_id=trace.tenant_id,
        agent_id=trace.agent_id,
        user_id=trace.user_id,
        original_intent=trace.original_intent,
        status=trace.status,
        started_at=trace.started_at,
        completed_at=trace.completed_at,
        summary=trace.summary,
        metadata_json=payload_service.sanitize_payload(trace.metadata_json),
        steps=[
            TraceStepResponse(
                id=step.id,
                trace_id=step.trace_id,
                step_number=step.step_number,
                type=step.type,
                content=step.content,
                metadata_json=payload_service.sanitize_payload(step.metadata_json),
                created_at=step.created_at,
            )
            for step in steps
        ],
    )
