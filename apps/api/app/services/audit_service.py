from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.enums import AuditActorType
from app.models import AuditEvent
from app.services.payload_service import PayloadService


payload_service = PayloadService()


class AuditService:
    def create_event(
        self,
        db: Session,
        *,
        tenant_id: str,
        actor_type: AuditActorType,
        actor_id: str | None,
        event_type: str,
        resource_type: str,
        resource_id: str | None,
        metadata: dict | None = None,
        ip_address: str | None = None,
    ) -> AuditEvent:
        event = AuditEvent(
            tenant_id=tenant_id,
            actor_type=actor_type,
            actor_id=actor_id,
            event_type=event_type,
            resource_type=resource_type,
            resource_id=resource_id,
            metadata_json=payload_service.sanitize_payload(metadata or {}),
            ip_address=ip_address,
        )
        db.add(event)
        db.flush()
        return event
