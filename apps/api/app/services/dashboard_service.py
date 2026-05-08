from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.enums import AgentStatus, ApprovalStatus, ToolCallStatus
from app.models import Agent, AuditEvent, ApprovalRequest, ToolCall
from app.schemas.audit import AuditEventResponse
from app.schemas.dashboard import DashboardOverview
from app.services.payload_service import PayloadService


class DashboardService:
    def __init__(self, payload_service: PayloadService | None = None) -> None:
        self.payload_service = payload_service or PayloadService()

    def overview(self, db: Session, *, tenant_id: str) -> DashboardOverview:
        total_agents = db.scalar(select(func.count()).select_from(Agent).where(Agent.tenant_id == tenant_id)) or 0
        active_agents = (
            db.scalar(
                select(func.count()).select_from(Agent).where(
                    Agent.tenant_id == tenant_id,
                    Agent.status == AgentStatus.ACTIVE,
                )
            )
            or 0
        )
        pending_approvals = (
            db.scalar(
                select(func.count()).select_from(ApprovalRequest).where(
                    ApprovalRequest.tenant_id == tenant_id,
                    ApprovalRequest.status == ApprovalStatus.PENDING,
                )
            )
            or 0
        )
        blocked_actions = (
            db.scalar(
                select(func.count()).select_from(ToolCall).where(
                    ToolCall.tenant_id == tenant_id,
                    ToolCall.status == ToolCallStatus.BLOCKED,
                )
            )
            or 0
        )
        high_risk_tool_calls = (
            db.scalar(
                select(func.count()).select_from(ToolCall).where(
                    ToolCall.tenant_id == tenant_id,
                    ToolCall.risk_score >= 65,
                )
            )
            or 0
        )
        recent_events = list(
            db.scalars(
                select(AuditEvent)
                .where(AuditEvent.tenant_id == tenant_id)
                .order_by(AuditEvent.created_at.desc())
                .limit(10)
            )
        )
        return DashboardOverview(
            total_agents=total_agents,
            active_agents=active_agents,
            pending_approvals=pending_approvals,
            blocked_actions=blocked_actions,
            high_risk_tool_calls=high_risk_tool_calls,
            recent_audit_events=[
                AuditEventResponse(
                    id=item.id,
                    tenant_id=item.tenant_id,
                    actor_type=item.actor_type,
                    actor_id=item.actor_id,
                    event_type=item.event_type,
                    resource_type=item.resource_type,
                    resource_id=item.resource_id,
                    metadata_json=self.payload_service.sanitize_payload(item.metadata_json),
                    ip_address=item.ip_address,
                    event_hash=item.event_hash,
                    previous_event_hash=item.previous_event_hash,
                    hash_algorithm=item.hash_algorithm,
                    chain_scope=item.chain_scope,
                    sequence_number=item.sequence_number,
                    anchored_at=item.anchored_at,
                    created_at=item.created_at,
                )
                for item in recent_events
            ],
        )
