"""add job reliability foundation

Revision ID: 0009_add_job_reliability_foundation
Revises: 0008_add_audit_integrity_chain
Create Date: 2026-05-03 11:50:00

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0009_add_job_reliability_foundation"
down_revision = "0008_add_audit_integrity_chain"
branch_labels = None
depends_on = None

worker_status_enum = postgresql.ENUM(
    "running",
    "stale",
    "stopped",
    name="workerstatus",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    worker_status_enum.create(bind, checkfirst=True)

    with op.batch_alter_table("jobs") as batch_op:
        batch_op.add_column(sa.Column("locked_by", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("dead_letter_reason", sa.String(length=512), nullable=True))
    op.create_index("ix_jobs_lease_expires_at", "jobs", ["lease_expires_at"])

    op.create_table(
        "workers",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("worker_id", sa.String(length=255), nullable=False),
        sa.Column("hostname", sa.String(length=255), nullable=False),
        sa.Column("process_id", sa.Integer(), nullable=True),
        sa.Column("status", worker_status_enum, nullable=False),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("stopped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("worker_id", name="uq_workers_worker_id"),
    )
    op.create_index("ix_workers_worker_id", "workers", ["worker_id"])
    op.create_index("ix_workers_status", "workers", ["status"])
    op.create_index("ix_workers_last_heartbeat_at", "workers", ["last_heartbeat_at"])


def downgrade() -> None:
    op.drop_index("ix_workers_last_heartbeat_at", table_name="workers")
    op.drop_index("ix_workers_status", table_name="workers")
    op.drop_index("ix_workers_worker_id", table_name="workers")
    op.drop_table("workers")

    op.drop_index("ix_jobs_lease_expires_at", table_name="jobs")

    with op.batch_alter_table("jobs") as batch_op:
        batch_op.drop_column("dead_letter_reason")
        batch_op.drop_column("lease_expires_at")
        batch_op.drop_column("locked_at")
        batch_op.drop_column("locked_by")

    bind = op.get_bind()
    worker_status_enum.drop(bind, checkfirst=True)
