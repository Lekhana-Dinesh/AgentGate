from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import ScheduledTaskScheduleKind, ScheduledTaskType
from app.db.base import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enum_types import enum_value_type


class ScheduledTask(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "scheduled_tasks"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_scheduled_tasks_tenant_name"),
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_scheduled_tasks_tenant_idempotency_key"),
        Index("ix_scheduled_tasks_tenant_id", "tenant_id"),
        Index("ix_scheduled_tasks_enabled", "enabled"),
        Index("ix_scheduled_tasks_task_type", "task_type"),
        Index("ix_scheduled_tasks_next_run_at", "next_run_at"),
    )

    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    task_type: Mapped[ScheduledTaskType] = mapped_column(enum_value_type(ScheduledTaskType), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    schedule_kind: Mapped[ScheduledTaskScheduleKind] = mapped_column(
        enum_value_type(ScheduledTaskScheduleKind),
        nullable=False,
    )
    interval_seconds: Mapped[int | None] = mapped_column(nullable=True)
    cron_expression: Mapped[str | None] = mapped_column(String(128), nullable=True)
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    config: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    tenant = relationship("Tenant", back_populates="scheduled_tasks")
