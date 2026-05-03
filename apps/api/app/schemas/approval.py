from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.core.enums import ApprovalStatus
from app.schemas.gateway import ToolCallResponse
from app.schemas.integration import ApprovalNotificationStatus
from app.schemas.job import ApprovalExecutionStatus


class ApprovalDecisionRequest(BaseModel):
    approver_comment: str | None = Field(default=None, max_length=2000)
    execute_now: bool = False


class ApprovalRequestResponse(BaseModel):
    id: str
    tenant_id: str
    tool_call_id: str
    requested_by_agent_id: str
    assigned_to_user_id: str | None
    status: ApprovalStatus
    reason: str
    approver_comment: str | None
    created_at: datetime
    decided_at: datetime | None
    tool_call: ToolCallResponse | None = None
    notification_status: ApprovalNotificationStatus | None = None
    execution_status: ApprovalExecutionStatus | None = None
