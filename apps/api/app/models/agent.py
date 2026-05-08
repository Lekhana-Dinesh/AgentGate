from __future__ import annotations

from sqlalchemy import ForeignKey, Index, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import AgentEnvironment, AgentStatus, RiskBand
from app.db.base import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enum_types import enum_value_type


class Agent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "agents"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_agents_tenant_name"),
        Index("ix_agents_tenant_id", "tenant_id"),
        Index("ix_agents_status", "status"),
    )

    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(String(1000), default="", nullable=False)
    owner_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    environment: Mapped[AgentEnvironment] = mapped_column(enum_value_type(AgentEnvironment), nullable=False)
    status: Mapped[AgentStatus] = mapped_column(enum_value_type(AgentStatus), default=AgentStatus.ACTIVE)
    purpose: Mapped[str] = mapped_column(String(1000), default="", nullable=False)
    allowed_tools: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    allowed_data_classes: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    risk_level: Mapped[RiskBand] = mapped_column(enum_value_type(RiskBand), default=RiskBand.MEDIUM, nullable=False)

    tenant = relationship("Tenant", back_populates="agents")
    owner = relationship("User")
    api_keys = relationship("AgentAPIKey", back_populates="agent")
