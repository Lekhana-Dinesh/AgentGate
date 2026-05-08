from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Index, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import RiskBand, ToolType
from app.db.base import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enum_types import enum_value_type


class Tool(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "tools"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_tools_tenant_name"),
        Index("ix_tools_tenant_id", "tenant_id"),
    )

    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[ToolType] = mapped_column(enum_value_type(ToolType), nullable=False)
    description: Mapped[str] = mapped_column(String(1000), default="", nullable=False)
    base_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    config: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    risk_level: Mapped[RiskBand] = mapped_column(enum_value_type(RiskBand), default=RiskBand.MEDIUM, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    tenant = relationship("Tenant", back_populates="tools")
