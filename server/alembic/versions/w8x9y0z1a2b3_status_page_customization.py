"""Add public status page customization fields to monitor_groups.

Revision ID: w8x9y0z1a2b3
Revises: v7w8x9y0z1a2
Create Date: 2026-04-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "w8x9y0z1a2b3"
down_revision: str | None = "v7w8x9y0z1a2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("monitor_groups", sa.Column("public_title", sa.String(255), nullable=True))
    op.add_column("monitor_groups", sa.Column("public_description", sa.Text(), nullable=True))
    op.add_column("monitor_groups", sa.Column("public_logo_url", sa.String(500), nullable=True))
    op.add_column("monitor_groups", sa.Column("public_accent_color", sa.String(7), nullable=True))
    op.add_column("monitor_groups", sa.Column("public_custom_css", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("monitor_groups", "public_custom_css")
    op.drop_column("monitor_groups", "public_accent_color")
    op.drop_column("monitor_groups", "public_logo_url")
    op.drop_column("monitor_groups", "public_description")
    op.drop_column("monitor_groups", "public_title")
