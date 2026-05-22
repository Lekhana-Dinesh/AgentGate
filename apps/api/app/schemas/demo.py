from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.core.enums import ApprovalStatus, TraceStatus
from app.schemas.audit import AuditEventResponse
from app.schemas.gateway import GatewayDecisionResponse, ToolCallResponse
from app.schemas.policy import PolicySimulationResponse


class DemoEvidenceLinks(BaseModel):
    trace_path: str
    approvals_path: str
    tool_calls_path: str
    audit_path: str


class DemoApprovalSummary(BaseModel):
    approval_id: str
    status: ApprovalStatus
    reviewer_email: str
    approver_comment: str | None
    execute_now: bool
    decided_at: datetime | None


class GitHubGovernedDemoResponse(BaseModel):
    scenario: Literal["github_governed_workflow"]
    trace_id: str
    trace_status: TraceStatus
    trace_summary: str
    simulation: PolicySimulationResponse
    governed_attempt: GatewayDecisionResponse
    approval: DemoApprovalSummary
    tool_call: ToolCallResponse
    audit_events: list[AuditEventResponse]
    execution_mode: Literal["demo_safe_mock", "live_connector", "unsupported"]
    no_live_external_call: bool
    evidence_links: DemoEvidenceLinks
