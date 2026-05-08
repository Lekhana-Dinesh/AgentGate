from __future__ import annotations

from sqlalchemy import Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin


class Tenant(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "tenants"
    __table_args__ = (Index("ix_tenants_slug", "slug", unique=True),)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False)
    plan: Mapped[str] = mapped_column(String(64), nullable=False)

    users = relationship("User", back_populates="tenant")
    oidc_configs = relationship("TenantOIDCConfig", back_populates="tenant")
    audit_export_configs = relationship("AuditExportConfig", back_populates="tenant")
    audit_integrity_checkpoints = relationship("AuditIntegrityCheckpoint", back_populates="tenant")
    scheduled_tasks = relationship("ScheduledTask", back_populates="tenant")
    agents = relationship("Agent", back_populates="tenant")
    tools = relationship("Tool", back_populates="tenant")
    policies = relationship("Policy", back_populates="tenant")
