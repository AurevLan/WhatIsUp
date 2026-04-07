"""add signal alert channel type

Revision ID: q2r3s4t5u6v7
Revises: p1q2r3s4t5u6
Create Date: 2026-04-07 09:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = 'q2r3s4t5u6v7'
down_revision: Union[str, None] = 'p1q2r3s4t5u6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE alert_channel_type ADD VALUE IF NOT EXISTS 'signal'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values; this is a no-op.
    pass
