"""DiscoverySource last-scan feedback columns (plan E, E-1).

Revision ID: 8d9e0f1a2b3c
Revises: 7c8d9e0f1a2b
Create Date: 2026-08-29

Additive, all nullable — the discovery feedback loop was blind: creating a
source produced no visible signal until the first heartbeat/push cycle
completed, so a broken source and a healthy-but-quiet one looked identical.
`last_scan_at`/`last_scan_target_count` are set unconditionally by
`push_discovery` on every accepted snapshot (including an empty one), and
`last_scan_probe_id` records which probe actually ran it — see
`models/discovery.py`'s docstring on why that's not just `probe_id`.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8d9e0f1a2b3c"
down_revision: str | None = "7c8d9e0f1a2b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "discovery_sources",
        sa.Column("last_scan_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "discovery_sources",
        sa.Column("last_scan_target_count", sa.Integer(), nullable=True),
    )
    op.add_column(
        "discovery_sources",
        sa.Column("last_scan_probe_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_discovery_sources_last_scan_probe_id",
        "discovery_sources",
        "probes",
        ["last_scan_probe_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_discovery_sources_last_scan_probe_id",
        "discovery_sources",
        type_="foreignkey",
    )
    op.drop_column("discovery_sources", "last_scan_probe_id")
    op.drop_column("discovery_sources", "last_scan_target_count")
    op.drop_column("discovery_sources", "last_scan_at")
