from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.enums import (
    AgentEnvironment,
    AgentStatus,
    ApprovalStatus,
    AuditActorType,
    PolicyDecision,
    PolicySeverity,
    RiskBand,
    ToolCallStatus,
    ToolType,
    TraceStatus,
    TraceStepType,
    UserRole,
)


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class MessageResponse(BaseModel):
    message: str


class PolicyCondition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: Literal[
        "tool_name",
        "action_name",
        "recipient_domain",
        "repo_trust",
        "data_classification",
        "risk_score",
        "environment",
        "amount",
        "discount_percent",
        "row_count",
        "intent_mismatch",
    ]
    operator: Literal["equals", "contains", "greater_than"]
    value: Any

    @model_validator(mode="after")
    def validate_rule(self) -> "PolicyCondition":
        numeric_fields = {"risk_score", "amount", "discount_percent", "row_count"}
        boolean_fields = {"intent_mismatch"}
        enum_fields = {"recipient_domain", "environment", "repo_trust"}
        text_fields = {"tool_name", "action_name", "data_classification"}

        if self.operator == "greater_than":
            if self.field not in numeric_fields:
                raise ValueError(f"greater_than is not supported for {self.field}.")
            if not isinstance(self.value, (int, float)):
                raise ValueError("greater_than requires a numeric value.")
            if self.field == "risk_score" and not 0 <= float(self.value) <= 100:
                raise ValueError("risk_score thresholds must stay between 0 and 100.")
            if self.field in {"amount", "discount_percent", "row_count"} and float(self.value) < 0:
                raise ValueError(f"{self.field} thresholds must be non-negative.")

        if self.field in boolean_fields and self.operator != "equals":
            raise ValueError(f"{self.field} only supports equals.")
        if self.field in boolean_fields and not isinstance(self.value, bool):
            raise ValueError(f"{self.field} requires a boolean value.")

        if self.field in enum_fields and self.operator not in {"equals", "contains"}:
            raise ValueError(f"{self.field} does not support {self.operator}.")
        if self.field == "recipient_domain" and self.value not in {"internal", "external"}:
            raise ValueError("recipient_domain must be internal or external.")
        if self.field == "environment" and self.value not in {
            "development",
            "staging",
            "production",
        }:
            raise ValueError("environment must be development, staging, or production.")
        if self.field == "repo_trust" and self.value not in {
            "internal",
            "external",
            "public",
            "unknown",
        }:
            raise ValueError("repo_trust must be internal, external, public, or unknown.")
        if self.field in text_fields:
            if self.operator not in {"equals", "contains"}:
                raise ValueError(f"{self.field} does not support {self.operator}.")
            if not isinstance(self.value, str) or not self.value.strip():
                raise ValueError(f"{self.field} requires a non-empty string value.")

        return self


class PolicyConditionSet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    match: Literal["all", "any"] = "all"
    rules: list[PolicyCondition] = Field(min_length=1)


class AuditEventSummary(ORMModel):
    id: str
    actor_type: AuditActorType
    actor_id: str | None
    event_type: str
    resource_type: str
    resource_id: str | None
    metadata_json: dict = Field(alias="metadata")
    ip_address: str | None
    created_at: datetime
