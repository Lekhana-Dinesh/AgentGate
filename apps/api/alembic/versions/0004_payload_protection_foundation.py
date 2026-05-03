"""add payload protection foundation columns

Revision ID: 0004_payload_protection_foundation
Revises: 0003_add_github_tool_type
Create Date: 2026-05-02 18:30:00

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0004_payload_protection_foundation"
down_revision = "0003_add_github_tool_type"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("tool_calls") as batch_op:
        batch_op.add_column(sa.Column("payload_protection_version", sa.String(length=64), nullable=True))
        batch_op.add_column(
            sa.Column(
                "payload_retention_class",
                sa.String(length=64),
                nullable=False,
                server_default="standard",
            )
        )
        batch_op.add_column(sa.Column("payload_expires_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(
            sa.Column(
                "payload_redaction_status",
                sa.String(length=64),
                nullable=False,
                server_default="sanitized",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("tool_calls") as batch_op:
        batch_op.drop_column("payload_redaction_status")
        batch_op.drop_column("payload_expires_at")
        batch_op.drop_column("payload_retention_class")
        batch_op.drop_column("payload_protection_version")
