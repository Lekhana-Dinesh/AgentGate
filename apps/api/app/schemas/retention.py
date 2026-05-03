from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import PayloadRetentionClass
from app.schemas.job import JobResponse
from app.services.retention_service import RetentionPurgeResult, RetentionStatusSummary


class RetentionPurgeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dry_run: bool = True
    limit: int = Field(default=100, ge=1, le=1000)
    retention_classes: list[PayloadRetentionClass] = Field(default_factory=list)
    tool_name: str | None = None
    tool_call_ids: list[str] = Field(default_factory=list)


class RetentionStatusResponse(BaseModel):
    eligible: int
    purged: int
    legal_hold: int
    failed: int
    protected_active: int


class RetentionPurgeResultResponse(BaseModel):
    dry_run: bool
    requested: int
    eligible: int
    purged: int
    skipped_non_expired: int
    skipped_legal_hold: int
    already_purged: int
    failed: int
    tool_call_ids: list[str] = Field(default_factory=list)
    failed_tool_call_ids: list[str] = Field(default_factory=list)


class RetentionPurgeResponse(BaseModel):
    dry_run: bool
    dispatch_mode: str
    job: JobResponse
    result: RetentionPurgeResultResponse | None = None


def serialize_retention_status(summary: RetentionStatusSummary) -> RetentionStatusResponse:
    return RetentionStatusResponse(**summary.to_payload())


def serialize_retention_result(result: RetentionPurgeResult | dict | None) -> RetentionPurgeResultResponse | None:
    if result is None:
        return None
    payload = result.to_payload() if isinstance(result, RetentionPurgeResult) else result
    return RetentionPurgeResultResponse(**payload)
