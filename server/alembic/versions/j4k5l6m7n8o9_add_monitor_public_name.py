"""Add public_name column to monitors.

Cap v2, étape 5c — optional visitor-facing name for a monitor, distinct from
the operator's internal `name` (which the public status page falls back to,
so this column changes nothing for a monitor that never sets it).

Revision ID: j4k5l6m7n8o9
Revises: i3j4k5l6m7n8
Create Date: 2026-09-06
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "j4k5l6m7n8o9"
down_revision: str | None = "i3j4k5l6m7n8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "monitors",
        sa.Column("public_name", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("monitors", "public_name")
