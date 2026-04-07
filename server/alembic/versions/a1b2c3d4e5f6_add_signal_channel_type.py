"""add signal alert channel type

Revision ID: a1b2c3d4e5f6
Revises: 283efc2c973a
Create Date: 2026-04-07 09:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '283efc2c973a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE alert_channel_type ADD VALUE IF NOT EXISTS 'signal'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values; this is a no-op.
    pass
