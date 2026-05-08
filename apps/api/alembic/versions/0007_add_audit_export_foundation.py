"""add audit export foundation

Revision ID: 0007_add_audit_export_foundation
Revises: 0006_add_tenant_oidc_foundation
Create Date: 2026-05-03 16:00:00

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0007_add_audit_export_foundation"
down_revision = "0006_add_tenant_oidc_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    destination_type_enum = postgresql.ENUM(
        "webhook",
        "splunk_hec",
        "datadog",
        "http_json",
        "custom_placeholder",
        name="auditexportdestinationtype",
        create_type=False,
    )
    destination_type_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "audit_export_configs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("destination_type", destination_type_enum, nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("endpoint_url", sa.String(length=1000), nullable=False),
        sa.Column("secret_ref", sa.String(length=255), nullable=True),
        sa.Column("token_env_var", sa.String(length=255), nullable=True),
        sa.Column("event_type_filters", sa.JSON(), nullable=False),
        sa.Column("severity_filters", sa.JSON(), nullable=False),
        sa.Column("max_batch_size", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("last_exported_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_exported_event_id", sa.String(length=36), nullable=True),
        sa.Column("last_export_job_id", sa.String(length=36), nullable=True),
        sa.Column("last_export_status", sa.String(length=64), nullable=True),
        sa.Column("last_error", sa.String(length=2000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "name", name="uq_audit_export_configs_tenant_name"),
    )
    op.create_index("ix_audit_export_configs_tenant_id", "audit_export_configs", ["tenant_id"])
    op.create_index("ix_audit_export_configs_enabled", "audit_export_configs", ["enabled"])
    op.create_index(
        "ix_audit_export_configs_destination_type",
        "audit_export_configs",
        ["destination_type"],
    )


def downgrade() -> None:
    op.drop_index("ix_audit_export_configs_destination_type", table_name="audit_export_configs")
    op.drop_index("ix_audit_export_configs_enabled", table_name="audit_export_configs")
    op.drop_index("ix_audit_export_configs_tenant_id", table_name="audit_export_configs")
    op.drop_table("audit_export_configs")

    destination_type_enum = postgresql.ENUM(
        "webhook",
        "splunk_hec",
        "datadog",
        "http_json",
        "custom_placeholder",
        name="auditexportdestinationtype",
        create_type=False,
    )
    destination_type_enum.drop(op.get_bind(), checkfirst=True)
