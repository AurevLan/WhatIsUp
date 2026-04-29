"""V2-02-07 — Probe outbound IP intelligence: self-reported IP + ASN.

Adds two columns to ``probes`` to enable detection of proxy/NAT/VPN setups:
  - self_reported_ip   : the IP the probe sees itself egressing through (via
                          api.ipify.org / icanhazip.com), reported on heartbeat.
  - self_reported_asn  : ASN resolved from self_reported_ip (Cymru lookup).

When self_reported_ip differs from the existing public_ip column (which is the
IP the central server observes on the heartbeat connection), an intermediate
hop is rewriting the source — flagged in the UI.

Revision ID: j2k3l4m5n6o7
Revises: h0i1j2k3l4m5
Create Date: 2026-04-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "j2k3l4m5n6o7"
down_revision: str | None = "h0i1j2k3l4m5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("probes", sa.Column("self_reported_ip", sa.String(length=45), nullable=True))
    op.add_column("probes", sa.Column("self_reported_asn", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("probes", "self_reported_asn")
    op.drop_column("probes", "self_reported_ip")
