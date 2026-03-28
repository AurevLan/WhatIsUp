"""Smart alerts & correlations: root cause tagging, correlation patterns,
group/dependency/pattern correlation, auto-alert presets, threshold suggestions.

Revision ID: i1j2k3l4m5n6
Revises: h1i2j3k4l5m6
Create Date: 2026-03-28 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "i1j2k3l4m5n6"
down_revision = "h1i2j3k4l5m6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── IncidentGroup: root cause tagging + correlation type ─────────────
    op.add_column(
        "incident_groups",
        sa.Column(
            "root_cause_monitor_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("monitors.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "incident_groups",
        sa.Column("correlation_type", sa.String(30), nullable=True),
    )

    # ── Correlation patterns table ───────────────────────────────────────
    op.create_table(
        "correlation_patterns",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "monitor_a_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("monitors.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "monitor_b_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("monitors.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("co_occurrence_count", sa.Integer, default=1, nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_correlation_pattern_pair",
        "correlation_patterns",
        ["monitor_a_id", "monitor_b_id"],
        unique=True,
    )
    op.create_index(
        "ix_correlation_pattern_count",
        "correlation_patterns",
        ["co_occurrence_count"],
    )


def downgrade() -> None:
    op.drop_index("ix_correlation_pattern_count", table_name="correlation_patterns")
    op.drop_index("ix_correlation_pattern_pair", table_name="correlation_patterns")
    op.drop_table("correlation_patterns")
    op.drop_column("incident_groups", "correlation_type")
    op.drop_column("incident_groups", "root_cause_monitor_id")
