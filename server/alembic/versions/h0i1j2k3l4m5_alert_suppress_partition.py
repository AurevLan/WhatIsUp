"""V2-02-02 — Add suppress_on_network_partition flag to alert_rules.

When True, dispatch_alert short-circuits if the incident's network_verdict is
network_partition_asn or network_partition_geo, so on-call doesn't get paged
for transit-level outages.

Revision ID: h0i1j2k3l4m5
Revises: g9h0i1j2k3l4
Create Date: 2026-04-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "h0i1j2k3l4m5"
down_revision: str | None = "g9h0i1j2k3l4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "alert_rules",
        sa.Column(
            "suppress_on_network_partition",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("alert_rules", "suppress_on_network_partition")
