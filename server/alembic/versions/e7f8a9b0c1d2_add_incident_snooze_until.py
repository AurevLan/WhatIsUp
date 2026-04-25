"""Add snooze_until to incidents (T1-04).

Revision ID: e7f8a9b0c1d2
Revises: d6e7f8a9b0c1
Create Date: 2026-04-25

Snooze is distinct from ack: ack is open-ended ("I own this, stop paging me"),
snooze is time-bounded ("shut up for 1 h, then re-arm"). Stored on the incident
itself rather than a side table so the renotify path can filter with one
indexed predicate.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e7f8a9b0c1d2"
down_revision: str | None = "d6e7f8a9b0c1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "incidents",
        sa.Column("snooze_until", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_incidents_snooze_until", "incidents", ["snooze_until"]
    )


def downgrade() -> None:
    op.drop_index("ix_incidents_snooze_until", table_name="incidents")
    op.drop_column("incidents", "snooze_until")
