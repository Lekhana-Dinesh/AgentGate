from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.audit import register_audit_event_integrity_listeners
from app.core.enums import AuditActorType
from app.db.base import Base
from app.models.base import UUIDPrimaryKeyMixin, utcnow
from app.models.enum_types import enum_value_type


class AuditEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_tenant_id", "tenant_id"),
        Index("ix_audit_events_event_type", "event_type"),
        Index("ix_audit_events_created_at", "created_at"),
        Index("ix_audit_events_chain_scope", "chain_scope"),
        UniqueConstraint("tenant_id", "sequence_number", name="uq_audit_events_tenant_sequence"),
    )

    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    actor_type: Mapped[AuditActorType] = mapped_column(enum_value_type(AuditActorType), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    event_type: Mapped[str] = mapped_column(String(255), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(255), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict, nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    event_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    previous_event_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    hash_algorithm: Mapped[str | None] = mapped_column(String(64), nullable=True)
    chain_scope: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sequence_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    anchored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


register_audit_event_integrity_listeners(AuditEvent)
