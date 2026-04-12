"""Add device_tokens table for native push notifications.

Revision ID: r3s4t5u6v7w8
Revises: q2r3s4t5u6v7
Create Date: 2026-04-12 23:30:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "r3s4t5u6v7w8"
down_revision = "q2r3s4t5u6v7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The PG enum may already exist from a previously failed run of this same
    # migration — drop it first so the table CREATE can recreate it cleanly.
    op.execute("DROP TYPE IF EXISTS device_platform CASCADE")

    op.create_table(
        "device_tokens",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("token", sa.Text(), nullable=False),
        sa.Column(
            "platform",
            sa.Enum("android", "ios", "web", name="device_platform"),
            nullable=False,
            server_default="android",
        ),
        sa.Column("encryption_key", sa.Text(), nullable=False),
        sa.Column("label", sa.String(255), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_device_tokens_token", "device_tokens", ["token"], unique=True
    )


def downgrade() -> None:
    op.drop_index("ix_device_tokens_token", table_name="device_tokens")
    op.drop_table("device_tokens")
    sa.Enum(name="device_platform").drop(op.get_bind(), checkfirst=True)
