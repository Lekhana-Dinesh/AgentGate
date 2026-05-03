"""add tenant oidc foundation

Revision ID: 0006_add_tenant_oidc_foundation
Revises: 0005_add_job_queue_foundation
Create Date: 2026-05-03 11:00:00

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0006_add_tenant_oidc_foundation"
down_revision = "0005_add_job_queue_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("auth_provider", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("external_subject", sa.String(length=255), nullable=True))
        batch_op.create_index("ix_users_auth_provider", ["auth_provider"])
        batch_op.create_unique_constraint(
            "uq_users_tenant_auth_subject",
            ["tenant_id", "auth_provider", "external_subject"],
        )

    op.create_table(
        "tenant_oidc_configs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("provider_name", sa.String(length=255), nullable=False),
        sa.Column("issuer_url", sa.String(length=1000), nullable=False),
        sa.Column("client_id", sa.String(length=255), nullable=False),
        sa.Column("client_secret_ref", sa.String(length=255), nullable=True),
        sa.Column("client_secret_env_var", sa.String(length=255), nullable=True),
        sa.Column("redirect_uri", sa.String(length=1000), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("allowed_email_domains", sa.JSON(), nullable=False),
        sa.Column("role_mapping", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "provider_name", name="uq_tenant_oidc_configs_tenant_provider"),
    )
    op.create_index("ix_tenant_oidc_configs_tenant_id", "tenant_oidc_configs", ["tenant_id"])
    op.create_index("ix_tenant_oidc_configs_enabled", "tenant_oidc_configs", ["enabled"])


def downgrade() -> None:
    op.drop_index("ix_tenant_oidc_configs_enabled", table_name="tenant_oidc_configs")
    op.drop_index("ix_tenant_oidc_configs_tenant_id", table_name="tenant_oidc_configs")
    op.drop_table("tenant_oidc_configs")

    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_constraint("uq_users_tenant_auth_subject", type_="unique")
        batch_op.drop_index("ix_users_auth_provider")
        batch_op.drop_column("external_subject")
        batch_op.drop_column("auth_provider")
