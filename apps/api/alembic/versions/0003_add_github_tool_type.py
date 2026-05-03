"""add github tool type

Revision ID: 0003_add_github_tool_type
Revises: 0002_api_key_lifecycle_and_tool_call_trace
Create Date: 2026-05-02 12:00:00

"""

from __future__ import annotations

from alembic import op


revision = "0003_add_github_tool_type"
down_revision = "0002_api_key_lifecycle_and_tool_call_trace"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TYPE tooltype ADD VALUE IF NOT EXISTS 'github'")


def downgrade() -> None:
    # PostgreSQL enum value removal is intentionally not attempted here.
    # Reverting this migration requires a manual enum recreation if needed.
    return None
