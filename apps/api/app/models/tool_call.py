from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Index, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import ToolCallStatus
from app.db.base import Base
from app.models.base import UUIDPrimaryKeyMixin, utcnow


class ToolCall(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "tool_calls"
    __table_args__ = (
        Index("ix_tool_calls_tenant_id", "tenant_id"),
        Index("ix_tool_calls_agent_id", "agent_id"),
        Index("ix_tool_calls_status", "status"),
        Index("ix_tool_calls_trace_id", "trace_id"),
    )

    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    trace_id: Mapped[str | None] = mapped_column(
        ForeignKey("execution_traces.id", ondelete="SET NULL"), nullable=True
    )
    tool_name: Mapped[str] = mapped_column(String(255), nullable=False)
    action_name: Mapped[str] = mapped_column(String(255), nullable=False)
    request_payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    response_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    payload_protection_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payload_retention_class: Mapped[str] = mapped_column(String(64), default="standard", nullable=False)
    payload_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    payload_redaction_status: Mapped[str] = mapped_column(String(64), default="sanitized", nullable=False)
    status: Mapped[ToolCallStatus] = mapped_column(Enum(ToolCallStatus), nullable=False)
    risk_score: Mapped[float] = mapped_column(Float, nullable=False)
    decision_reason: Mapped[str] = mapped_column(String(2000), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
