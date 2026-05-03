from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Enum, ForeignKey, Index, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import AuditExportDestinationType
from app.db.base import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin


class AuditExportConfig(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "audit_export_configs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_audit_export_configs_tenant_name"),
        Index("ix_audit_export_configs_tenant_id", "tenant_id"),
        Index("ix_audit_export_configs_enabled", "enabled"),
        Index("ix_audit_export_configs_destination_type", "destination_type"),
    )

    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    destination_type: Mapped[AuditExportDestinationType] = mapped_column(
        Enum(AuditExportDestinationType),
        nullable=False,
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    endpoint_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    secret_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    token_env_var: Mapped[str | None] = mapped_column(String(255), nullable=True)
    event_type_filters: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    severity_filters: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    max_batch_size: Mapped[int] = mapped_column(default=100, nullable=False)
    last_exported_at: Mapped[datetime | None] = mapped_column(nullable=True)
    last_exported_event_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    last_export_job_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    last_export_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(2000), nullable=True)

    tenant = relationship("Tenant", back_populates="audit_export_configs")
