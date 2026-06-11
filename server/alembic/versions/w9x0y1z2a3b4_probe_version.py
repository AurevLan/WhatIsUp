"""Probe fleet versioning — probes self-report their agent version.

Adds ``probes.version`` (nullable string), populated at each heartbeat.
The UI compares it against the server version to flag outdated probes —
a stale probe silently skews check verdicts (e.g. ignores newer monitor
config fields such as ``dns_nameservers``).

Revision ID: w9x0y1z2a3b4
Revises: v8w9x0y1z2a3
Create Date: 2026-06-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "w9x0y1z2a3b4"
down_revision = "v8w9x0y1z2a3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("probes", sa.Column("version", sa.String(length=32), nullable=True))


def downgrade() -> None:
    op.drop_column("probes", "version")
