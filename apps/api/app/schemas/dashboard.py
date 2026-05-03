from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.audit import AuditEventResponse


class DashboardOverview(BaseModel):
    total_agents: int
    active_agents: int
    pending_approvals: int
    blocked_actions: int
    high_risk_tool_calls: int
    recent_audit_events: list[AuditEventResponse] = Field(default_factory=list)

