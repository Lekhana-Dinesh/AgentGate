from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field, computed_field, model_validator

from app.core.enums import AgentEnvironment, AgentStatus, RiskBand
from app.schemas.common import ORMModel


class AgentCreate(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    description: str = Field(default="", max_length=1000)
    owner_user_id: str | None = None
    environment: AgentEnvironment
    purpose: str = Field(default="", max_length=1000)
    allowed_tools: list[str] = Field(default_factory=list)
    allowed_data_classes: list[str] = Field(default_factory=list)
    risk_level: RiskBand = RiskBand.MEDIUM


class AgentUpdate(BaseModel):
    description: str | None = Field(default=None, max_length=1000)
    owner_user_id: str | None = None
    environment: AgentEnvironment | None = None
    purpose: str | None = Field(default=None, max_length=1000)
    allowed_tools: list[str] | None = None
    allowed_data_classes: list[str] | None = None
    risk_level: RiskBand | None = None
    status: AgentStatus | None = None


class AgentResponse(ORMModel):
    id: str
    tenant_id: str
    name: str
    description: str
    owner_user_id: str | None
    environment: AgentEnvironment
    status: AgentStatus
    purpose: str
    allowed_tools: list[str]
    allowed_data_classes: list[str]
    risk_level: RiskBand
    created_at: datetime
    updated_at: datetime


class AgentAPIKeyCreate(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    expires_in_days: int | None = Field(default=90, ge=1, le=365)
    scopes: list[Literal["gateway:invoke"]] = Field(default_factory=lambda: ["gateway:invoke"])

    @model_validator(mode="after")
    def validate_key_request(self) -> "AgentAPIKeyCreate":
        if not self.scopes:
            raise ValueError("At least one API key scope is required.")
        return self


class AgentAPIKeySummary(BaseModel):
    id: str
    name: str
    prefix: str
    created_at: datetime
    created_by_user_id: str | None
    scopes: list[str]
    expires_at: datetime | None
    last_used_at: datetime | None
    revoked_at: datetime | None

    @computed_field
    @property
    def is_active(self) -> bool:
        if self.revoked_at is not None:
            return False
        if self.expires_at is None:
            return True
        expires_at = (
            self.expires_at
            if self.expires_at.tzinfo is not None
            else self.expires_at.replace(tzinfo=timezone.utc)
        )
        return expires_at > datetime.now(timezone.utc)


class AgentAPIKeyResponse(AgentAPIKeySummary):
    api_key: str
