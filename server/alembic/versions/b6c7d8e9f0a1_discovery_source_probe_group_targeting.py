"""DiscoverySource probe-group targeting + sticky election (plan E, E-2).

Revision ID: b6c7d8e9f0a1
Revises: 8d9e0f1a2b3c
Create Date: 2026-08-29

`probe_id` becomes nullable — a source now targets *either* one probe or one
`ProbeGroup` (`probe_group_id`), enforced by `ck_discovery_sources_probe_xor_group`.
`elected_probe_id` is the sticky server-side pick (E-0-2) of which group
member runs a `port_scan`/`dns_zone` source; meaningless without a group
(`ck_discovery_sources_elected_requires_group`). No backfill: every existing
row already has `probe_id` set and `probe_group_id` NULL, which satisfies the
new CHECK as-is.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b6c7d8e9f0a1"
down_revision: str | None = "8d9e0f1a2b3c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("discovery_sources", "probe_id", existing_type=sa.Uuid(), nullable=True)

    op.add_column(
        "discovery_sources",
        sa.Column("probe_group_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "discovery_sources",
        sa.Column("elected_probe_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_discovery_sources_probe_group_id",
        "discovery_sources",
        "probe_groups",
        ["probe_group_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_discovery_sources_elected_probe_id",
        "discovery_sources",
        "probes",
        ["elected_probe_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_discovery_sources_probe_group_id", "discovery_sources", ["probe_group_id"])
    op.create_check_constraint(
        "ck_discovery_sources_probe_xor_group",
        "discovery_sources",
        "(probe_id IS NOT NULL AND probe_group_id IS NULL) "
        "OR (probe_id IS NULL AND probe_group_id IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_discovery_sources_elected_requires_group",
        "discovery_sources",
        "elected_probe_id IS NULL OR probe_group_id IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_discovery_sources_elected_requires_group", "discovery_sources", type_="check"
    )
    op.drop_constraint("ck_discovery_sources_probe_xor_group", "discovery_sources", type_="check")
    op.drop_index("ix_discovery_sources_probe_group_id", table_name="discovery_sources")
    op.drop_constraint(
        "fk_discovery_sources_elected_probe_id", "discovery_sources", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_discovery_sources_probe_group_id", "discovery_sources", type_="foreignkey"
    )
    op.drop_column("discovery_sources", "elected_probe_id")
    op.drop_column("discovery_sources", "probe_group_id")
    op.alter_column("discovery_sources", "probe_id", existing_type=sa.Uuid(), nullable=False)
