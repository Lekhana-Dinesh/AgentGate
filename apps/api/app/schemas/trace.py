from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.core.enums import TraceStatus, TraceStepType


class TraceCreate(BaseModel):
    agent_id: str
    user_id: str | None = None
    original_intent: str = Field(min_length=3, max_length=2000)
    metadata: dict = Field(default_factory=dict)


class TraceStepCreate(BaseModel):
    type: TraceStepType
    content: str = Field(min_length=1, max_length=4000)
    metadata: dict = Field(default_factory=dict)


class TraceStepResponse(BaseModel):
    id: str
    trace_id: str
    step_number: int
    type: TraceStepType
    content: str
    metadata_json: dict
    created_at: datetime


class TraceResponse(BaseModel):
    id: str
    tenant_id: str
    agent_id: str
    user_id: str | None
    original_intent: str
    status: TraceStatus
    started_at: datetime
    completed_at: datetime | None
    summary: str
    metadata_json: dict
    steps: list[TraceStepResponse] = Field(default_factory=list)

