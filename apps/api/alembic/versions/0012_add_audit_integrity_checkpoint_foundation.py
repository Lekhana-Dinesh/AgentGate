"""add audit integrity checkpoint foundation

Revision ID: 0012_add_audit_integrity_checkpoint_foundation
Revises: 0011_add_user_identity_lifecycle_foundation
Create Date: 2026-05-06 18:20:00

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0012_add_audit_integrity_checkpoint_foundation"
down_revision = "0011_add_user_identity_lifecycle_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_integrity_checkpoints",
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column(
            "checkpoint_type",
            sa.Enum(
                "local",
                "object_storage",
                "custom_placeholder",
                name="auditintegritycheckpointtype",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("chain_scope", sa.String(length=255), nullable=False),
        sa.Column("from_sequence_number", sa.Integer(), nullable=False),
        sa.Column("to_sequence_number", sa.Integer(), nullable=False),
        sa.Column("from_event_id", sa.String(length=36), nullable=False),
        sa.Column("to_event_id", sa.String(length=36), nullable=False),
        sa.Column("checkpoint_hash", sa.String(length=128), nullable=True),
        sa.Column("previous_checkpoint_hash", sa.String(length=128), nullable=True),
        sa.Column("event_count", sa.Integer(), nullable=False),
        sa.Column("destination_ref", sa.String(length=1000), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "anchored",
                "failed",
                name="auditintegritycheckpointstatus",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("anchored_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_audit_integrity_checkpoints_tenant_id",
        "audit_integrity_checkpoints",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        "ix_audit_integrity_checkpoints_status",
        "audit_integrity_checkpoints",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_audit_integrity_checkpoints_chain_scope",
        "audit_integrity_checkpoints",
        ["chain_scope"],
        unique=False,
    )
    op.create_index(
        "ix_audit_integrity_checkpoints_created_at",
        "audit_integrity_checkpoints",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_audit_integrity_checkpoints_created_at", table_name="audit_integrity_checkpoints")
    op.drop_index("ix_audit_integrity_checkpoints_chain_scope", table_name="audit_integrity_checkpoints")
    op.drop_index("ix_audit_integrity_checkpoints_status", table_name="audit_integrity_checkpoints")
    op.drop_index("ix_audit_integrity_checkpoints_tenant_id", table_name="audit_integrity_checkpoints")
    op.drop_table("audit_integrity_checkpoints")
