"""Probe API key prefix index — kill the O(n) bcrypt fleet scan on probe auth.

Adds ``probes.api_key_prefix`` (nullable, unique-indexed). New/rotated probe
keys use the format ``wiu_<prefix>.<secret>``; the non-secret ``<prefix>`` is
stored here so ``get_current_probe`` resolves the single candidate probe by
index and runs exactly ONE bcrypt verification, instead of scanning the whole
fleet.

Backward compatible: existing probes keep ``api_key_prefix = NULL`` and a legacy
``wiu_<secret>`` key. They authenticate via the (now NULL-restricted) bcrypt
scan fallback until their next ``POST /probes/{id}/rotate-key``, which populates
this column and moves them onto the fast path.

Revision ID: y1z2a3b4c5d6
Revises: x0y1z2a3b4c5
Create Date: 2026-07-02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "y1z2a3b4c5d6"
down_revision = "x0y1z2a3b4c5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "probes",
        sa.Column("api_key_prefix", sa.String(length=32), nullable=True),
    )
    op.create_index(
        op.f("ix_probes_api_key_prefix"),
        "probes",
        ["api_key_prefix"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_probes_api_key_prefix"), table_name="probes")
    op.drop_column("probes", "api_key_prefix")
