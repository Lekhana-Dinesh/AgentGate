from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import WorkerStatus
from app.db.base import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin, utcnow
from app.models.enum_types import enum_value_type


class Worker(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "workers"
    __table_args__ = (
        Index("ix_workers_worker_id", "worker_id"),
        Index("ix_workers_status", "status"),
        Index("ix_workers_last_heartbeat_at", "last_heartbeat_at"),
        UniqueConstraint("worker_id", name="uq_workers_worker_id"),
    )

    worker_id: Mapped[str] = mapped_column(String(255), nullable=False)
    hostname: Mapped[str] = mapped_column(String(255), nullable=False)
    process_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[WorkerStatus] = mapped_column(
        enum_value_type(WorkerStatus),
        default=WorkerStatus.RUNNING,
        nullable=False,
    )
    last_heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict, nullable=False)
