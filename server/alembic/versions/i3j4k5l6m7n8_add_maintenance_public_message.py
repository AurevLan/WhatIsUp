"""Add public_message column to maintenance_windows.

Cap v2, étape 5a — optional visitor-facing text for a maintenance window,
distinct from the operator-only name/description.

Revision ID: i3j4k5l6m7n8
Revises: h2i3j4k5l6m7
Create Date: 2026-09-06
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "i3j4k5l6m7n8"
down_revision: str | None = "h2i3j4k5l6m7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "maintenance_windows",
        sa.Column("public_message", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("maintenance_windows", "public_message")
