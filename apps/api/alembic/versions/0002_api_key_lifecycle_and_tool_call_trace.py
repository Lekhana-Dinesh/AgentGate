"""api key lifecycle and tool call trace linkage

Revision ID: 0002_api_key_lifecycle_and_tool_call_trace
Revises: 0001_initial_schema
Create Date: 2026-05-01 00:30:00

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0002_api_key_lifecycle_and_tool_call_trace"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("agent_api_keys") as batch_op:
        batch_op.add_column(
            sa.Column(
                "scopes",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'[\"gateway:invoke\"]'"),
            )
        )
        batch_op.add_column(sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.create_index("ix_agent_api_keys_agent_id", ["agent_id"], unique=False)
        batch_op.create_index("ix_agent_api_keys_expires_at", ["expires_at"], unique=False)

    with op.batch_alter_table("tool_calls") as batch_op:
        batch_op.add_column(sa.Column("trace_id", sa.String(length=36), nullable=True))
        batch_op.create_foreign_key(
            "fk_tool_calls_trace_id_execution_traces",
            "execution_traces",
            ["trace_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index("ix_tool_calls_trace_id", ["trace_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("tool_calls") as batch_op:
        batch_op.drop_index("ix_tool_calls_trace_id")
        batch_op.drop_constraint("fk_tool_calls_trace_id_execution_traces", type_="foreignkey")
        batch_op.drop_column("trace_id")

    with op.batch_alter_table("agent_api_keys") as batch_op:
        batch_op.drop_index("ix_agent_api_keys_expires_at")
        batch_op.drop_index("ix_agent_api_keys_agent_id")
        batch_op.drop_column("expires_at")
        batch_op.drop_column("scopes")
