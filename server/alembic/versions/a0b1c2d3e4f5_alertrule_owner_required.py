"""Backfill and enforce alert_rules.owner_id NOT NULL.

Revision ID: a0b1c2d3e4f5
Revises: y0z1a2b3c4d5
Create Date: 2026-04-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a0b1c2d3e4f5"
down_revision: str | None = "y0z1a2b3c4d5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Backfill from linked monitor
    op.execute(
        sa.text(
            """
            UPDATE alert_rules
            SET owner_id = monitors.owner_id
            FROM monitors
            WHERE alert_rules.monitor_id = monitors.id
              AND alert_rules.owner_id IS NULL
            """
        )
    )

    # Backfill from linked group
    op.execute(
        sa.text(
            """
            UPDATE alert_rules
            SET owner_id = monitor_groups.owner_id
            FROM monitor_groups
            WHERE alert_rules.group_id = monitor_groups.id
              AND alert_rules.owner_id IS NULL
            """
        )
    )

    # Orphaned rules (no monitor, no group, no owner) can't be attributed
    # safely — delete them. Such rules never resolved a target anyway.
    op.execute(sa.text("DELETE FROM alert_rules WHERE owner_id IS NULL"))

    # Enforce NOT NULL going forward
    op.alter_column(
        "alert_rules",
        "owner_id",
        existing_type=sa.Uuid(),
        nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "alert_rules",
        "owner_id",
        existing_type=sa.Uuid(),
        nullable=True,
    )
