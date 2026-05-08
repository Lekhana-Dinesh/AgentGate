from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from app.core.enums import AuditActorType
from app.schemas.common import ORMModel


class AuditEventResponse(ORMModel):
    id: str
    tenant_id: str
    actor_type: AuditActorType
    actor_id: str | None
    event_type: str
    resource_type: str
    resource_id: str | None
    metadata_json: dict
    ip_address: str | None
    event_hash: str | None = None
    previous_event_hash: str | None = None
    hash_algorithm: str | None = None
    chain_scope: str | None = None
    sequence_number: int | None = None
    anchored_at: datetime | None = None
    created_at: datetime
