"""Hourly rollup table for check_results (plan V2, A-2).

Revision ID: f7a8b9c0d1e2
Revises: e6f7a8b9c0d1
Create Date: 2026-08-07

A-1 made the raw table prunable; it did not make it small. A 90-day analytical
query still walks 115 k rows per monitor (4.9 M for the public status page),
which is why ``compute_daily_history_bulk`` was measured at 9.5 s. The same
window as hourly buckets is ~2 200 rows per monitor.

The table is created empty. ``services/rollup.py`` backfills it from the raw
rows on the background loop, a week per run, so the migration itself stays
instant regardless of how much history the deployment holds.

Grain is ``(monitor_id, bucket)`` — see the model docstring for why the plan's
per-probe grain was dropped (uptime is a cross-probe consensus, and percentiles
do not pool).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f7a8b9c0d1e2"
down_revision: str | None = "e6f7a8b9c0d1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "check_rollups_1h",
        sa.Column("monitor_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("bucket", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("up_count", sa.Integer(), nullable=False),
        sa.Column("down_count", sa.Integer(), nullable=False),
        sa.Column("timeout_count", sa.Integer(), nullable=False),
        sa.Column("error_count", sa.Integer(), nullable=False),
        sa.Column("internal_windows", sa.Integer(), nullable=False),
        sa.Column("internal_up_windows", sa.Integer(), nullable=False),
        sa.Column("external_windows", sa.Integer(), nullable=False),
        sa.Column("external_up_windows", sa.Integer(), nullable=False),
        sa.Column("rt_count", sa.Integer(), nullable=False),
        sa.Column("rt_sum", sa.Float(), nullable=True),
        sa.Column("rt_min", sa.Float(), nullable=True),
        sa.Column("rt_max", sa.Float(), nullable=True),
        sa.Column("p50_ms", sa.Float(), nullable=True),
        sa.Column("p95_ms", sa.Float(), nullable=True),
        sa.Column("p99_ms", sa.Float(), nullable=True),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["monitor_id"], ["monitors.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("monitor_id", "bucket"),
    )
    # The PK covers per-monitor range scans; this serves retention deleting a
    # cutoff across all monitors (plan V2, A-4).
    op.create_index("ix_check_rollups_1h_bucket", "check_rollups_1h", ["bucket"])


def downgrade() -> None:
    op.drop_index("ix_check_rollups_1h_bucket", table_name="check_rollups_1h")
    op.drop_table("check_rollups_1h")
