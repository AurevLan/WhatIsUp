"""Discovered service dismissed_reason (plan D, D-3).

Revision ID: 1a2b3c4d5e6f
Revises: 0574394e5c64
Create Date: 2026-08-23

`POST /discovery/services/{id}/dismiss` gains an optional `reason` — a plain
nullable String column, cleared whenever a row leaves `dismissed` (accepted,
or reappeared and flipped back by the reconciler) so it never misreports why
a service is currently in the review queue.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "1a2b3c4d5e6f"
down_revision: str | None = "0574394e5c64"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "discovered_services",
        sa.Column("dismissed_reason", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("discovered_services", "dismissed_reason")
