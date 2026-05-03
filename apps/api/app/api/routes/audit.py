from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import AuditEvent
from app.schemas.audit import AuditEventResponse
from app.services.payload_service import PayloadService

router = APIRouter()
payload_service = PayloadService()


@router.get("/events", response_model=list[AuditEventResponse])
def list_audit_events(
    agent_id: str | None = None,
    user_id: str | None = None,
    event_type: str | None = None,
    start_date: datetime | None = Query(default=None),
    end_date: datetime | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[AuditEventResponse]:
    query = select(AuditEvent).where(AuditEvent.tenant_id == current_user.tenant_id)
    if event_type:
        query = query.where(AuditEvent.event_type == event_type)
    if start_date:
        query = query.where(AuditEvent.created_at >= start_date)
    if end_date:
        query = query.where(AuditEvent.created_at <= end_date)
    events = list(db.scalars(query.order_by(AuditEvent.created_at.desc())))
    if agent_id:
        events = [
            event
            for event in events
            if event.actor_id == agent_id or event.metadata_json.get("agent_id") == agent_id
        ]
    if user_id:
        events = [
            event
            for event in events
            if event.actor_id == user_id or event.metadata_json.get("user_id") == user_id
        ]
    events = events[offset : offset + limit]
    return [
        AuditEventResponse(
            id=item.id,
            tenant_id=item.tenant_id,
            actor_type=item.actor_type,
            actor_id=item.actor_id,
            event_type=item.event_type,
            resource_type=item.resource_type,
            resource_id=item.resource_id,
            metadata_json=payload_service.sanitize_payload(item.metadata_json),
            ip_address=item.ip_address,
            created_at=item.created_at,
        )
        for item in events
    ]
