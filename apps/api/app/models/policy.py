from __future__ import annotations

from sqlalchemy import Boolean, Enum, ForeignKey, Index, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import PolicyDecision, PolicySeverity
from app.db.base import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin


class Policy(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "policies"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_policies_tenant_name"),
        Index("ix_policies_tenant_id", "tenant_id"),
        Index("ix_policies_enabled", "enabled"),
    )

    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(String(1000), default="", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    severity: Mapped[PolicySeverity] = mapped_column(Enum(PolicySeverity), nullable=False)
    conditions: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    decision: Mapped[PolicyDecision] = mapped_column(Enum(PolicyDecision), nullable=False)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    tenant = relationship("Tenant", back_populates="policies")
    creator = relationship("User")

