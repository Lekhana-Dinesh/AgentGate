from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.core.enums import PolicyDecision, PolicySeverity
from app.schemas.common import ORMModel, PolicyConditionSet


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

