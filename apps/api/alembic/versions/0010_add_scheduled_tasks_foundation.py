"""add scheduled tasks foundation

Revision ID: 0010_add_scheduled_tasks_foundation
Revises: 0009_add_job_reliability_foundation
Create Date: 2026-05-04 14:20:00

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0010_add_scheduled_tasks_foundation"
down_revision = "0009_add_job_reliability_foundation"
branch_labels = None
depends_on = None

scheduled_task_type_enum = postgresql.ENUM(
    "retention_purge",
    "audit_export",
    "audit_integrity_verify",
    "connector_health_check",
    name="scheduledtasktype",
    create_type=False,
)
scheduled_task_schedule_kind_enum = postgresql.ENUM(
    "interval",
    "cron",
    name="scheduledtaskschedulekind",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == "postgresql":
        op.execute("ALTER TYPE jobtype ADD VALUE IF NOT EXISTS 'audit_integrity_verify.placeholder'")
        op.execute("ALTER TYPE jobtype ADD VALUE IF NOT EXISTS 'connector_health_check.placeholder'")

    scheduled_task_type_enum.create(bind, checkfirst=True)
    scheduled_task_schedule_kind_enum.create(bind, checkfirst=True)

    op.create_table(
        "scheduled_tasks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("task_type", scheduled_task_type_enum, nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("schedule_kind", scheduled_task_schedule_kind_enum, nullable=False),
        sa.Column("interval_seconds", sa.Integer(), nullable=True),
        sa.Column("cron_expression", sa.String(length=128), nullable=True),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status", sa.String(length=64), nullable=True),
        sa.Column("last_error", sa.String(length=2000), nullable=True),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "name", name="uq_scheduled_tasks_tenant_name"),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_scheduled_tasks_tenant_idempotency_key"),
    )
    op.create_index("ix_scheduled_tasks_tenant_id", "scheduled_tasks", ["tenant_id"])
    op.create_index("ix_scheduled_tasks_enabled", "scheduled_tasks", ["enabled"])
    op.create_index("ix_scheduled_tasks_task_type", "scheduled_tasks", ["task_type"])
    op.create_index("ix_scheduled_tasks_next_run_at", "scheduled_tasks", ["next_run_at"])


def downgrade() -> None:
    op.drop_index("ix_scheduled_tasks_next_run_at", table_name="scheduled_tasks")
    op.drop_index("ix_scheduled_tasks_task_type", table_name="scheduled_tasks")
    op.drop_index("ix_scheduled_tasks_enabled", table_name="scheduled_tasks")
    op.drop_index("ix_scheduled_tasks_tenant_id", table_name="scheduled_tasks")
    op.drop_table("scheduled_tasks")

    bind = op.get_bind()
    scheduled_task_schedule_kind_enum.drop(bind, checkfirst=True)
    scheduled_task_type_enum.drop(bind, checkfirst=True)
