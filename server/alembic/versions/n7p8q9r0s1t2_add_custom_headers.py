"""Add custom_headers to monitors

Revision ID: n7p8q9r0s1t2
Revises: k3l4m5n6o7p8
Create Date: 2026-05-02 22:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "n7p8q9r0s1t2"
down_revision = "k3l4m5n6o7p8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("monitors", sa.Column("custom_headers", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("monitors", "custom_headers")
