"""add user identity lifecycle foundation

Revision ID: 0011_add_user_identity_lifecycle_foundation
Revises: 0010_add_scheduled_tasks_foundation
Create Date: 2026-05-06 12:00:00

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0011_add_user_identity_lifecycle_foundation"
down_revision = "0010_add_scheduled_tasks_foundation"
branch_labels = None
depends_on = None

user_provisioned_source_enum = postgresql.ENUM(
    "local",
    "oidc",
    "scim",
    "system",
    name="userprovisionedsource",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    user_provisioned_source_enum.create(bind, checkfirst=True)

    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(
            sa.Column(
                "provisioned_source",
                user_provisioned_source_enum,
                nullable=False,
                server_default="local",
            )
        )
        batch_op.add_column(sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("deactivation_reason", sa.String(length=500), nullable=True))
        batch_op.create_index("ix_users_provisioned_source", ["provisioned_source"])


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_index("ix_users_provisioned_source")
        batch_op.drop_column("deactivation_reason")
        batch_op.drop_column("deactivated_at")
        batch_op.drop_column("provisioned_source")

    bind = op.get_bind()
    user_provisioned_source_enum.drop(bind, checkfirst=True)
