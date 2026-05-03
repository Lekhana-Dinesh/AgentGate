from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.job import JobSummary


class ApprovalNotificationStatus(BaseModel):
    provider: Literal["slack"]
    status: Literal[
        "disabled",
        "not_attempted",
        "queued",
        "running",
        "sent",
        "failed",
        "retry_exhausted",
        "cancelled",
        "unconfigured",
    ]
    job_id: str | None = None
    job: JobSummary | None = None
    attempts: int | None = None
    max_attempts: int | None = None
    event_type: str | None = None
    message: str | None = None
    error_code: str | None = None
    request_id: str | None = None
    channel: str | None = None
    created_at: datetime | None = None


class SlackIntegrationHealthResponse(BaseModel):
    provider: Literal["slack"] = "slack"
    enabled: bool
    configured: bool
    status: Literal["disabled", "ready", "degraded", "unconfigured"]
    token_env_var: str
    default_channel: str | None = None
    probe_performed: bool = False
    can_connect: bool | None = None
    details: dict = Field(default_factory=dict)
