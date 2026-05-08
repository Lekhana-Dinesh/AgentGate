from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import AuditIntegrityCheckpointStatus, AuditIntegrityCheckpointType
from app.schemas.common import ORMModel
from app.schemas.job import JobResponse


class AuditIntegrityIssue(BaseModel):
    code: str
    detail: str
    event_id: str | None = None
    sequence_number: int | None = None


class AuditIntegrityStatusResponse(BaseModel):
    tenant_id: str
    chain_scope: str
    hash_algorithm: str
    status: Literal["empty", "legacy_only", "anchored", "anchored_with_legacy"]
    total_events: int
    anchored_events: int
    legacy_unanchored_events: int
    latest_sequence_number: int | None = None
    latest_event_id: str | None = None
    latest_event_hash: str | None = None
    latest_anchored_at: datetime | None = None


class AuditIntegrityVerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_event_id: str | None = Field(default=None, max_length=36)
    end_event_id: str | None = Field(default=None, max_length=36)
    start_date: datetime | None = None
    end_date: datetime | None = None


class AuditIntegrityVerifyResponse(BaseModel):
    tenant_id: str
    chain_scope: str
    hash_algorithm: str
    status: Literal["empty", "legacy_only", "verified", "verified_with_legacy", "broken"]
    chain_valid: bool
    boundary_limited: bool = False
    total_events: int
    anchored_events: int
    legacy_unanchored_events: int
    verified_events: int
    first_verified_event_id: str | None = None
    last_verified_event_id: str | None = None
    latest_sequence_number: int | None = None
    latest_event_id: str | None = None
    latest_event_hash: str | None = None
    latest_anchored_at: datetime | None = None
    issues: list[AuditIntegrityIssue] = Field(default_factory=list)


class AuditIntegrityBackfillRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dry_run: bool = True


class AuditIntegrityBackfillResponse(BaseModel):
    tenant_id: str
    chain_scope: str
    hash_algorithm: str
    dry_run: bool
    total_events: int
    rebuilt_events: int
    anchored_events_before: int
    anchored_events_after: int
    legacy_unanchored_events_before: int
    legacy_unanchored_events_after: int
    latest_sequence_number: int | None = None
    latest_event_id: str | None = None
    latest_event_hash: str | None = None


class AuditIntegrityCheckpointCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AuditIntegrityCheckpointResponse(ORMModel):
    id: str
    tenant_id: str
    checkpoint_type: AuditIntegrityCheckpointType
    chain_scope: str
    from_sequence_number: int
    to_sequence_number: int
    from_event_id: str
    to_event_id: str
    checkpoint_hash: str | None = None
    previous_checkpoint_hash: str | None = None
    event_count: int
    destination_ref: str | None = None
    status: AuditIntegrityCheckpointStatus
    created_at: datetime
    anchored_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AuditIntegrityCheckpointJobResult(BaseModel):
    created: bool
    status: Literal["anchored", "failed", "no_new_events"]
    checkpoint_id: str | None = None
    checkpoint_status: AuditIntegrityCheckpointStatus | None = None
    event_count: int = 0
    from_sequence_number: int | None = None
    to_sequence_number: int | None = None
    checkpoint_hash: str | None = None


class AuditIntegrityCheckpointRunResponse(BaseModel):
    dispatch_mode: Literal["inline", "worker"]
    job: JobResponse
    result: AuditIntegrityCheckpointJobResult | None = None


class AuditIntegrityCheckpointVerifyResponse(BaseModel):
    checkpoint_id: str
    tenant_id: str
    status: Literal["verified", "broken"]
    chain_valid: bool
    checkpoint_hash_valid: bool
    external_anchor_valid: bool | None = None
    stored_checkpoint_hash: str | None = None
    recomputed_checkpoint_hash: str | None = None
    verified_at: datetime
    issues: list[AuditIntegrityIssue] = Field(default_factory=list)
