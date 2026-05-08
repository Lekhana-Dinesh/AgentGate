from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import UserProvisionedSource, UserRole
from app.db.base import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enum_types import enum_value_type


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("tenant_id", "email", name="uq_users_tenant_email"),
        UniqueConstraint(
            "tenant_id",
            "auth_provider",
            "external_subject",
            name="uq_users_tenant_auth_subject",
        ),
        Index("ix_users_tenant_id", "tenant_id"),
        Index("ix_users_auth_provider", "auth_provider"),
        Index("ix_users_provisioned_source", "provisioned_source"),
    )

    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(512), nullable=False)
    auth_provider: Mapped[str | None] = mapped_column(String(255), nullable=True)
    external_subject: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[UserRole] = mapped_column(enum_value_type(UserRole), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    provisioned_source: Mapped[UserProvisionedSource] = mapped_column(
        enum_value_type(UserProvisionedSource),
        default=UserProvisionedSource.LOCAL,
        nullable=False,
    )
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deactivation_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    tenant = relationship("Tenant", back_populates="users")

    @property
    def status(self) -> str:
        return "active" if self.is_active else "deactivated"
