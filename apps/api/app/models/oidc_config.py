from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Index, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin


class TenantOIDCConfig(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "tenant_oidc_configs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "provider_name", name="uq_tenant_oidc_configs_tenant_provider"),
        Index("ix_tenant_oidc_configs_tenant_id", "tenant_id"),
        Index("ix_tenant_oidc_configs_enabled", "enabled"),
    )

    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    provider_name: Mapped[str] = mapped_column(String(255), nullable=False)
    issuer_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    client_id: Mapped[str] = mapped_column(String(255), nullable=False)
    client_secret_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    client_secret_env_var: Mapped[str | None] = mapped_column(String(255), nullable=True)
    redirect_uri: Mapped[str] = mapped_column(String(1000), nullable=False)
    scopes: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    allowed_email_domains: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    role_mapping: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    tenant = relationship("Tenant", back_populates="oidc_configs")
