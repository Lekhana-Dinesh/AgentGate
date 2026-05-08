"""add async job queue foundation

Revision ID: 0005_add_job_queue_foundation
Revises: 0004_payload_protection_foundation
Create Date: 2026-05-02 21:30:00

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0005_add_job_queue_foundation"
down_revision = "0004_payload_protection_foundation"
branch_labels = None
depends_on = None

job_type_enum = postgresql.ENUM(
    "approval_notification.slack",
    "approval_execution.tool_call",
    "audit_export.placeholder",
    "retention_purge.placeholder",
    name="jobtype",
    create_type=False,
)
job_status_enum = postgresql.ENUM(
    "queued",
    "running",
    "succeeded",
    "failed",
    "retry_exhausted",
    "cancelled",
    name="jobstatus",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    job_type_enum.create(bind, checkfirst=True)
    job_status_enum.create(bind, checkfirst=True)

    op.create_table(
        "jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("job_type", job_type_enum, nullable=False),
        sa.Column("status", job_status_enum, nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_error", sa.String(length=2000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_jobs_tenant_idempotency_key"),
    )
    op.create_index("ix_jobs_tenant_id", "jobs", ["tenant_id"])
    op.create_index("ix_jobs_job_type", "jobs", ["job_type"])
    op.create_index("ix_jobs_status", "jobs", ["status"])
    op.create_index("ix_jobs_next_run_at", "jobs", ["next_run_at"])


def downgrade() -> None:
    op.drop_index("ix_jobs_next_run_at", table_name="jobs")
    op.drop_index("ix_jobs_status", table_name="jobs")
    op.drop_index("ix_jobs_job_type", table_name="jobs")
    op.drop_index("ix_jobs_tenant_id", table_name="jobs")
    op.drop_table("jobs")

    bind = op.get_bind()
    job_status_enum.drop(bind, checkfirst=True)
    job_type_enum.drop(bind, checkfirst=True)
