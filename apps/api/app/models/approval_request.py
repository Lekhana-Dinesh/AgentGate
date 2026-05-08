from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import ApprovalStatus
from app.db.base import Base
from app.models.base import UUIDPrimaryKeyMixin, utcnow
from app.models.enum_types import enum_value_type


class ApprovalRequest(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "approval_requests"
    __table_args__ = (
        Index("ix_approval_requests_tenant_id", "tenant_id"),
        Index("ix_approval_requests_status", "status"),
    )

    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    tool_call_id: Mapped[str] = mapped_column(
        ForeignKey("tool_calls.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    requested_by_agent_id: Mapped[str] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    assigned_to_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[ApprovalStatus] = mapped_column(
        enum_value_type(ApprovalStatus), default=ApprovalStatus.PENDING, nullable=False
    )
    reason: Mapped[str] = mapped_column(String(2000), default="", nullable=False)
    approver_comment: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
