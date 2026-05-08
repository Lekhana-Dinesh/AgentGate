from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import TraceStatus
from app.db.base import Base
from app.models.base import UUIDPrimaryKeyMixin, utcnow
from app.models.enum_types import enum_value_type


class ExecutionTrace(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "execution_traces"
    __table_args__ = (
        Index("ix_execution_traces_tenant_id", "tenant_id"),
        Index("ix_execution_traces_agent_id", "agent_id"),
    )

    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    original_intent: Mapped[str] = mapped_column(String(2000), nullable=False)
    status: Mapped[TraceStatus] = mapped_column(enum_value_type(TraceStatus), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    summary: Mapped[str] = mapped_column(String(2000), default="", nullable=False)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict, nullable=False)
