"""Probe discovery capabilities (plan D, D-1).

Revision ID: 0574394e5c64
Revises: 579d759d9075
Create Date: 2026-08-17

Adds ``probes.discovery_capabilities`` — the source types (``docker``,
``port_scan``…) a probe declared itself able to run at its last heartbeat.
Nullable and additive only: a pre-D-1 probe never sends the field, and the
heartbeat endpoint only ever writes to this column when the field is present
in the request body (``model_fields_set``), so an old probe's heartbeat never
overwrites a previously-declared value with null. See ``models/probe.py``.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0574394e5c64"
down_revision: str | None = "579d759d9075"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.add_column(
        "probes",
        sa.Column("discovery_capabilities", _JSON, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("probes", "discovery_capabilities")
