from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.core.enums import PolicyDecision, PolicySeverity, RiskBand, ToolType
from app.schemas.common import ORMModel, PolicyConditionSet
from app.schemas.gateway import IntentCheckResult, RiskAssessmentResult


class PolicyCreate(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    description: str = Field(default="", max_length=1000)
    enabled: bool = True
    severity: PolicySeverity
    conditions: PolicyConditionSet
    decision: PolicyDecision


class PolicyUpdate(BaseModel):
    description: str | None = Field(default=None, max_length=1000)
    enabled: bool | None = None
    severity: PolicySeverity | None = None
    conditions: PolicyConditionSet | None = None
    decision: PolicyDecision | None = None


class PolicyResponse(ORMModel):
    id: str
    tenant_id: str
    name: str
    description: str
    enabled: bool
    severity: PolicySeverity
    conditions: PolicyConditionSet
    decision: PolicyDecision
    created_by: str | None
    created_at: datetime
    updated_at: datetime


class PolicySimulationPolicyInput(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    description: str = Field(default="", max_length=1000)
    enabled: bool = True
    severity: PolicySeverity
    conditions: PolicyConditionSet
    decision: PolicyDecision


class PolicySimulationRequest(BaseModel):
    agent_id: str
    original_intent: str = Field(min_length=3, max_length=2000)
    tool_name: str = Field(min_length=2, max_length=255)
    tool_type: ToolType | None = None
    action_name: str = Field(min_length=2, max_length=255)
    target_hint: str | None = Field(default=None, max_length=255)
    resource_hint: str | None = Field(default=None, max_length=255)
    arguments: dict[str, Any] = Field(default_factory=dict)
    data_classifications: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    policy_ids: list[str] = Field(default_factory=list)
    proposed_policies: list[PolicySimulationPolicyInput] = Field(default_factory=list)
    dry_run: Literal[True] = True


class PolicySimulationMatch(BaseModel):
    policy_id: str | None = None
    name: str
    severity: PolicySeverity
    decision: PolicyDecision
    source: Literal["saved", "proposed"]


class PolicySimulationResponse(BaseModel):
    dry_run: Literal[True] = True
    advisory: Literal[True] = True
    decision: PolicyDecision
    approval_required: bool
    risk_band: RiskBand
    intent: IntentCheckResult
    risk: RiskAssessmentResult
    matched_policies: list[PolicySimulationMatch] = Field(default_factory=list)
    major_decision_factors: list[str] = Field(default_factory=list)
    policy_reasons: list[str] = Field(default_factory=list)
    explanation: str
    no_external_action_executed: Literal[True] = True
    no_job_enqueued: Literal[True] = True
    no_approval_created: Literal[True] = True
