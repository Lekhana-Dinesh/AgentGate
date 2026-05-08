from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import AuditIntegrityCheckpointStatus, AuditIntegrityCheckpointType
from app.db.base import Base
from app.models.base import UUIDPrimaryKeyMixin, utcnow
from app.models.enum_types import enum_value_type


class AuditIntegrityCheckpoint(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "audit_integrity_checkpoints"
    __table_args__ = (
        Index("ix_audit_integrity_checkpoints_tenant_id", "tenant_id"),
        Index("ix_audit_integrity_checkpoints_status", "status"),
        Index("ix_audit_integrity_checkpoints_chain_scope", "chain_scope"),
        Index("ix_audit_integrity_checkpoints_created_at", "created_at"),
    )

    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    checkpoint_type: Mapped[AuditIntegrityCheckpointType] = mapped_column(
        enum_value_type(AuditIntegrityCheckpointType),
        nullable=False,
    )
    chain_scope: Mapped[str] = mapped_column(String(255), nullable=False)
    from_sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    to_sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    from_event_id: Mapped[str] = mapped_column(String(36), nullable=False)
    to_event_id: Mapped[str] = mapped_column(String(36), nullable=False)
    checkpoint_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    previous_checkpoint_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    event_count: Mapped[int] = mapped_column(Integer, nullable=False)
    destination_ref: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    status: Mapped[AuditIntegrityCheckpointStatus] = mapped_column(
        enum_value_type(AuditIntegrityCheckpointStatus),
        nullable=False,
    )
    anchored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    tenant = relationship("Tenant", back_populates="audit_integrity_checkpoints")
