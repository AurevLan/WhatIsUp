"""custom_metrics table

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-03-13 00:01:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "c9d0e1f2a3b4"
down_revision = "b8c9d0e1f2a3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "custom_metrics",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "monitor_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("monitors.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("metric_name", sa.String(100), nullable=False),
        sa.Column("value", sa.Float, nullable=False),
        sa.Column("unit", sa.String(50), nullable=True),
        sa.Column("pushed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_custom_metrics_monitor_time",
        "custom_metrics",
        ["monitor_id", "pushed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_custom_metrics_monitor_time", table_name="custom_metrics")
    op.drop_table("custom_metrics")
