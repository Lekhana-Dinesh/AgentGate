from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.core.enums import RiskBand, ToolType
from app.schemas.common import ORMModel


class ToolCreate(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    type: ToolType
    description: str = Field(default="", max_length=1000)
    base_url: str | None = Field(default=None, max_length=1000)
    config: dict = Field(default_factory=dict)
    risk_level: RiskBand = RiskBand.MEDIUM
    enabled: bool = True


class ToolUpdate(BaseModel):
    description: str | None = Field(default=None, max_length=1000)
    base_url: str | None = Field(default=None, max_length=1000)
    config: dict | None = None
    risk_level: RiskBand | None = None
    enabled: bool | None = None


class ToolResponse(ORMModel):
    id: str
    tenant_id: str
    name: str
    type: ToolType
    description: str
    base_url: str | None
    config: dict
    risk_level: RiskBand
    enabled: bool
    created_at: datetime
    updated_at: datetime


class ToolHealthResponse(BaseModel):
    tool_id: str
    tool_name: str
    tool_type: ToolType
    status: Literal["ready", "degraded", "unconfigured", "unsupported"]
    adapter: str
    auth_provider: str | None = None
    token_present: bool | None = None
    probe_performed: bool = False
    can_connect: bool | None = None
    details: dict = Field(default_factory=dict)
