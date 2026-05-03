"""Add discord/mattermost/teams alert channels + SSL pinning + chain min days.

Revision ID: s5t6u7v8w9x0
Revises: n7p8q9r0s1t2
Create Date: 2026-05-03 23:30:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "s5t6u7v8w9x0"
down_revision = "n7p8q9r0s1t2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Postgres enums require ALTER TYPE ADD VALUE outside a transaction in older versions,
    # but SQLAlchemy/asyncpg here run in the implicit Alembic transaction; IF NOT EXISTS
    # guards against duplicate runs.
    op.execute("ALTER TYPE alert_channel_type ADD VALUE IF NOT EXISTS 'discord'")
    op.execute("ALTER TYPE alert_channel_type ADD VALUE IF NOT EXISTS 'mattermost'")
    op.execute("ALTER TYPE alert_channel_type ADD VALUE IF NOT EXISTS 'teams'")

    op.add_column(
        "monitors",
        sa.Column("ssl_pin_sha256", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "monitors",
        sa.Column("ssl_min_chain_days", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("monitors", "ssl_min_chain_days")
    op.drop_column("monitors", "ssl_pin_sha256")
    # Postgres enum value removal requires recreating the type — left as no-op.
    # Rolling back the channel additions in a destructive way is more dangerous
    # than leaving the values present; users simply stop seeing them in the UI.
