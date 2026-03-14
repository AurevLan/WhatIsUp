"""status_subscriptions table

Revision ID: b8c9d0e1f2a3
Revises: d4e5f6a7b8c9
Create Date: 2026-03-13 00:00:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "b8c9d0e1f2a3"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "status_subscriptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "group_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("monitor_groups.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("token", sa.String(64), nullable=False),
        sa.Column("subscribed_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("token", name="uq_status_subscriptions_token"),
    )
    op.create_index(
        "ix_status_subscriptions_group_id",
        "status_subscriptions",
        ["group_id"],
    )
    op.create_index(
        "ix_status_subscriptions_group_email",
        "status_subscriptions",
        ["group_id", "email"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_table("status_subscriptions")
