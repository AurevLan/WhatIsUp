"""Discovered service dismissed_fingerprint (plan D, D-4).

Revision ID: 7c8d9e0f1a2b
Revises: 1a2b3c4d5e6f
Create Date: 2026-08-24

Supports re-proposing a `dismissed` service when what it *is* changes (not
its port/target, which is already baked into `normalized_target` and would
make it a different row entirely). `dismissed_fingerprint` is captured by
`dismiss()` from a stable, documented subset of `hints` (image, container
name, server header — see `services/discovery.py::dismissal_fingerprint`),
never recomputed from the live row: ingestion refreshes `hints` in place on
every push, so the baseline has to be pinned at the moment of the refusal.
NULL means "dismissed before this column existed, or never dismissed" — the
reconciler leaves those rows alone rather than re-proposing them based on a
baseline that was never actually captured.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7c8d9e0f1a2b"
down_revision: str | None = "1a2b3c4d5e6f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "discovered_services",
        sa.Column("dismissed_fingerprint", sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("discovered_services", "dismissed_fingerprint")
