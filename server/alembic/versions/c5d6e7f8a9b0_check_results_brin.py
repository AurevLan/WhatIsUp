"""Add BRIN index on check_results.checked_at (time-series range scans).

Revision ID: c5d6e7f8a9b0
Revises: z1a2b3c4d5e6
Create Date: 2026-04-23

Without this index, queries like `WHERE checked_at >= NOW() - INTERVAL '24h'`
fall back to a parallel Seq Scan on the whole table (~600 MB / 1.6M rows in
production). BRIN is ideal for append-only timestamp columns: a few KB per
GB of data, ~5x speedup on the list_monitors bulk aggregations.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "c5d6e7f8a9b0"
down_revision: str | None = "z1a2b3c4d5e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    # `pages_per_range=32` gives a good balance between index size and
    # range granularity for our typical check interval cadence.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_cr_checked_at_brin "
        "ON check_results USING BRIN (checked_at) WITH (pages_per_range = 32)"
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute("DROP INDEX IF EXISTS ix_cr_checked_at_brin")
