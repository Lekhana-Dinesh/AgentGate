from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, JSON, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import TraceStepType
from app.db.base import Base
from app.models.base import UUIDPrimaryKeyMixin, utcnow
from app.models.enum_types import enum_value_type


class TraceStep(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "trace_steps"
    __table_args__ = (
        UniqueConstraint("trace_id", "step_number", name="uq_trace_steps_trace_step"),
        Index("ix_trace_steps_trace_id", "trace_id"),
    )

    trace_id: Mapped[str] = mapped_column(
        ForeignKey("execution_traces.id", ondelete="CASCADE"), nullable=False
    )
    step_number: Mapped[int] = mapped_column(Integer, nullable=False)
    type: Mapped[TraceStepType] = mapped_column(enum_value_type(TraceStepType), nullable=False)
    content: Mapped[str] = mapped_column(String(4000), nullable=False)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
