"""V2-02-01 + V2-02-02 — ASN enrichment on probes + network verdict on incidents.

Adds to ``probes``:
  - public_ip            (varchar 45, nullable, indexed)   -- IPv4/IPv6 source IP
  - asn                  (integer, nullable, indexed)
  - asn_name             (varchar 255, nullable)
  - ixp_membership       (jsonb list, nullable)
  - asn_updated_at       (timestamptz, nullable)

Adds to ``incidents``:
  - network_verdict              (varchar 40, nullable, indexed)
  - network_verdict_computed_at  (timestamptz, nullable)

All columns are nullable — fully backwards-compatible. No backfill required;
the enrichment service will populate them on the next probe heartbeat.

Revision ID: g9h0i1j2k3l4
Revises: f8a9b0c1d2e3
Create Date: 2026-04-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "g9h0i1j2k3l4"
down_revision: str | None = "f8a9b0c1d2e3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_postgres() -> bool:
    return op.get_context().dialect.name == "postgresql"


def upgrade() -> None:
    jsonb_type = postgresql.JSONB(astext_type=sa.Text()) if _is_postgres() else sa.JSON()

    op.add_column("probes", sa.Column("public_ip", sa.String(length=45), nullable=True))
    op.add_column("probes", sa.Column("asn", sa.Integer(), nullable=True))
    op.add_column("probes", sa.Column("asn_name", sa.String(length=255), nullable=True))
    op.add_column("probes", sa.Column("ixp_membership", jsonb_type, nullable=True))
    op.add_column(
        "probes",
        sa.Column("asn_updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_probes_public_ip", "probes", ["public_ip"], unique=False)
    op.create_index("ix_probes_asn", "probes", ["asn"], unique=False)

    op.add_column(
        "incidents",
        sa.Column("network_verdict", sa.String(length=40), nullable=True),
    )
    op.add_column(
        "incidents",
        sa.Column(
            "network_verdict_computed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_incidents_network_verdict",
        "incidents",
        ["network_verdict"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_incidents_network_verdict", table_name="incidents")
    op.drop_column("incidents", "network_verdict_computed_at")
    op.drop_column("incidents", "network_verdict")

    op.drop_index("ix_probes_asn", table_name="probes")
    op.drop_index("ix_probes_public_ip", table_name="probes")
    op.drop_column("probes", "asn_updated_at")
    op.drop_column("probes", "ixp_membership")
    op.drop_column("probes", "asn_name")
    op.drop_column("probes", "asn")
    op.drop_column("probes", "public_ip")
