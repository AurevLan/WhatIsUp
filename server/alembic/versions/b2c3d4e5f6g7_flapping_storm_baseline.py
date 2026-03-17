"""Add per-monitor flapping settings, alert rule storm protection and baseline fields

Revision ID: b2c3d4e5f6g7
Revises: c1d2e3f4a5b6
Create Date: 2026-03-17 01:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

revision = "b2c3d4e5f6g7"
down_revision = "c1d2e3f4a5b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Per-monitor flapping thresholds
    op.add_column(
        "monitors",
        sa.Column("flap_threshold", sa.Integer(), nullable=False, server_default="5"),
    )
    op.add_column(
        "monitors",
        sa.Column("flap_window_minutes", sa.Integer(), nullable=False, server_default="10"),
    )

    # AlertRule storm protection
    op.add_column("alert_rules", sa.Column("storm_window_seconds", sa.Integer(), nullable=True))
    op.add_column("alert_rules", sa.Column("storm_max_alerts", sa.Integer(), nullable=True))

    # AlertRule baseline factor
    op.add_column("alert_rules", sa.Column("baseline_factor", sa.Float(), nullable=True))

    # New AlertCondition enum value (PostgreSQL only)
    op.execute(
        "ALTER TYPE alert_condition ADD VALUE IF NOT EXISTS 'response_time_above_baseline'"
    )


def downgrade() -> None:
    op.drop_column("alert_rules", "baseline_factor")
    op.drop_column("alert_rules", "storm_max_alerts")
    op.drop_column("alert_rules", "storm_window_seconds")
    op.drop_column("monitors", "flap_window_minutes")
    op.drop_column("monitors", "flap_threshold")
    # Note: removing an enum value in PostgreSQL requires recreating the type
    # — left as manual operation on downgrade
