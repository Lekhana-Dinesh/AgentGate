from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.core.enums import PolicyDecision, RiskBand, ToolCallStatus
from app.schemas.common import ORMModel
from app.services.payload_service import PayloadService


class ToolCallRequest(BaseModel):
    agent_id: str
    user_id: str | None = None
    delegated_user_id: str | None = None
    trace_id: str | None = None
    original_intent: str = Field(min_length=3, max_length=2000)
    tool_name: str = Field(min_length=2, max_length=255)
    action_name: str = Field(min_length=2, max_length=255)
    arguments: dict[str, Any] = Field(default_factory=dict)
    data_classifications: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class IntentCheckResult(BaseModel):
    intent_match: bool
    confidence: float
    explanation: str
    detected_mismatch_reasons: list[str] = Field(default_factory=list)


class RiskAssessmentFactor(BaseModel):
    key: str
    label: str
    category: Literal["baseline", "action", "environment", "recipient", "data", "amount", "policy", "intent"]
    weight: float
    explanation: str


class RiskAssessmentResult(BaseModel):
    score: float
    band: RiskBand
    reasons: list[str] = Field(default_factory=list)
    factors: list[RiskAssessmentFactor] = Field(default_factory=list)
    summary: str


class PolicyMatch(BaseModel):
    policy_id: str
    name: str
    severity: str
    decision: str


class PolicyEvaluationResult(BaseModel):
    decision: PolicyDecision
    matched_policies: list[PolicyMatch] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


class ToolCallResponse(ORMModel):
    id: str
    tenant_id: str
    agent_id: str
    user_id: str | None
    trace_id: str | None
    tool_name: str
    action_name: str
    request_payload: dict
    response_payload: dict | None
    payload_protection_version: str | None = None
    payload_retention_class: str
    payload_expires_at: datetime | None = None
    payload_redaction_status: str
    status: ToolCallStatus
    risk_score: float
    decision_reason: str
    created_at: datetime


class GatewayDecisionResponse(BaseModel):
    tool_call_id: str
    trace_id: str
    decision: PolicyDecision
    status: ToolCallStatus
    intent: IntentCheckResult
    risk: RiskAssessmentResult
    policies: PolicyEvaluationResult
    executed: bool
    output: dict[str, Any] | None = None


def serialize_tool_call(tool_call) -> ToolCallResponse:
    payload_service = PayloadService()
    request_payload = dict(tool_call.request_payload or {})
    request_payload.pop("execution_arguments", None)
    return ToolCallResponse(
        id=tool_call.id,
        tenant_id=tool_call.tenant_id,
        agent_id=tool_call.agent_id,
        user_id=tool_call.user_id,
        trace_id=tool_call.trace_id,
        tool_name=tool_call.tool_name,
        action_name=tool_call.action_name,
        request_payload=payload_service.sanitize_payload(request_payload),
        response_payload=payload_service.sanitize_payload(tool_call.response_payload)
        if tool_call.response_payload
        else None,
        payload_protection_version=tool_call.payload_protection_version,
        payload_retention_class=tool_call.payload_retention_class,
        payload_expires_at=tool_call.payload_expires_at,
        payload_redaction_status=tool_call.payload_redaction_status,
        status=tool_call.status,
        risk_score=tool_call.risk_score,
        decision_reason=tool_call.decision_reason,
        created_at=tool_call.created_at,
    )
