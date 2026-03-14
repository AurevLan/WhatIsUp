"""SLO / Error Budget fields on monitors

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-03-13 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "a7b8c9d0e1f2"
down_revision = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("monitors", sa.Column("slo_target", sa.Float(), nullable=True))
    op.add_column(
        "monitors",
        sa.Column(
            "slo_window_days",
            sa.Integer(),
            nullable=False,
            server_default="30",
        ),
    )


def downgrade() -> None:
    op.drop_column("monitors", "slo_window_days")
    op.drop_column("monitors", "slo_target")
