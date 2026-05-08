from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.enums import PayloadRetentionClass, ScheduledTaskScheduleKind, ScheduledTaskType
from app.schemas.common import ORMModel
from app.schemas.job import JobResponse


class ScheduledRetentionPurgeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dry_run: bool = False
    limit: int = Field(default=100, ge=1, le=1000)
    retention_classes: list[PayloadRetentionClass] = Field(default_factory=list)
    tool_name: str | None = Field(default=None, min_length=1, max_length=255)
    tool_call_ids: list[str] = Field(default_factory=list)


class ScheduledAuditExportConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    audit_export_config_id: str = Field(min_length=1, max_length=36)
    dry_run: bool = False


class ScheduledAuditIntegrityVerifyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_event_id: str | None = Field(default=None, max_length=36)
    end_event_id: str | None = Field(default=None, max_length=36)
    start_date: datetime | None = None
    end_date: datetime | None = None


class ScheduledAuditIntegrityCheckpointConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ScheduledConnectorHealthCheckConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_ids: list[str] = Field(default_factory=list)
    probe: bool = False


class ScheduledTaskBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=2, max_length=255)
    task_type: ScheduledTaskType
    enabled: bool = True
    schedule_kind: ScheduledTaskScheduleKind
    interval_seconds: int | None = Field(default=None, ge=60, le=60 * 60 * 24 * 365)
    cron_expression: str | None = Field(default=None, min_length=1, max_length=128)
    next_run_at: datetime | None = None
    config: dict[str, Any] = Field(default_factory=dict)

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return str(value or "").strip()

    @field_validator("cron_expression", mode="before")
    @classmethod
    def normalize_cron_expression(cls, value: str | None) -> str | None:
        normalized = str(value or "").strip()
        return normalized or None

    @field_validator("config", mode="before")
    @classmethod
    def normalize_config(cls, value: Any) -> dict[str, Any]:
        if value in (None, ""):
            return {}
        if not isinstance(value, dict):
            raise ValueError("config must be a JSON object.")
        return value

    @model_validator(mode="after")
    def validate_schedule_shape(self) -> "ScheduledTaskBase":
        if self.schedule_kind == ScheduledTaskScheduleKind.INTERVAL:
            if self.interval_seconds is None:
                raise ValueError("interval_seconds is required when schedule_kind=interval.")
            if self.cron_expression is not None:
                raise ValueError("cron_expression must be omitted when schedule_kind=interval.")
        else:
            if not self.cron_expression:
                raise ValueError("cron_expression is required when schedule_kind=cron.")
            if self.interval_seconds is not None:
                raise ValueError("interval_seconds must be omitted when schedule_kind=cron.")
        return self


class ScheduledTaskCreate(ScheduledTaskBase):
    pass


class ScheduledTaskUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=2, max_length=255)
    enabled: bool | None = None
    schedule_kind: ScheduledTaskScheduleKind | None = None
    interval_seconds: int | None = Field(default=None, ge=60, le=60 * 60 * 24 * 365)
    cron_expression: str | None = Field(default=None, min_length=1, max_length=128)
    next_run_at: datetime | None = None
    config: dict[str, Any] | None = None

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        normalized = str(value or "").strip()
        return normalized or None

    @field_validator("cron_expression", mode="before")
    @classmethod
    def normalize_cron_expression(cls, value: str | None) -> str | None:
        normalized = str(value or "").strip()
        return normalized or None

    @field_validator("config", mode="before")
    @classmethod
    def normalize_config(cls, value: Any) -> dict[str, Any] | None:
        if value is None:
            return None
        if not isinstance(value, dict):
            raise ValueError("config must be a JSON object.")
        return value


class ScheduledTaskResponse(ORMModel):
    id: str
    tenant_id: str
    name: str
    task_type: ScheduledTaskType
    enabled: bool
    schedule_kind: ScheduledTaskScheduleKind
    interval_seconds: int | None
    cron_expression: str | None
    next_run_at: datetime
    last_run_at: datetime | None
    last_status: str | None
    last_error: str | None
    idempotency_key: str
    config: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class ScheduledTaskRunNowResponse(BaseModel):
    dispatch_mode: str
    job: JobResponse
    scheduled_task: ScheduledTaskResponse
