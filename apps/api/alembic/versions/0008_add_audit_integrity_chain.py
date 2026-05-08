"""add audit integrity chain metadata

Revision ID: 0008_add_audit_integrity_chain
Revises: 0007_add_audit_export_foundation
Create Date: 2026-05-04 01:15:00

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0008_add_audit_integrity_chain"
down_revision = "0007_add_audit_export_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("audit_events") as batch_op:
        batch_op.add_column(sa.Column("event_hash", sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column("previous_event_hash", sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column("hash_algorithm", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("chain_scope", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("sequence_number", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("anchored_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.create_index("ix_audit_events_chain_scope", ["chain_scope"])
        batch_op.create_unique_constraint(
            "uq_audit_events_tenant_sequence",
            ["tenant_id", "sequence_number"],
        )


def downgrade() -> None:
    with op.batch_alter_table("audit_events") as batch_op:
        batch_op.drop_constraint("uq_audit_events_tenant_sequence", type_="unique")
        batch_op.drop_index("ix_audit_events_chain_scope")
        batch_op.drop_column("anchored_at")
        batch_op.drop_column("sequence_number")
        batch_op.drop_column("chain_scope")
        batch_op.drop_column("hash_algorithm")
        batch_op.drop_column("previous_event_hash")
        batch_op.drop_column("event_hash")
