"""add jira tool type foundation

Revision ID: 0013_add_jira_tool_type_foundation
Revises: 0012_add_audit_integrity_checkpoint_foundation
Create Date: 2026-05-07 00:00:00

"""

from __future__ import annotations

from alembic import op


revision = "0013_add_jira_tool_type_foundation"
down_revision = "0012_add_audit_integrity_checkpoint_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TYPE tooltype ADD VALUE IF NOT EXISTS 'jira'")


def downgrade() -> None:
    # PostgreSQL enum value removal is intentionally left as a no-op to avoid unsafe
    # type rewrites on live deployments. The application no longer depends on downgrade.
    return None
