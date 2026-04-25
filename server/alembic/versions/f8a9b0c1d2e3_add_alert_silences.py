"""Add alert_silences table (T1-01).

Revision ID: f8a9b0c1d2e3
Revises: e7f8a9b0c1d2
Create Date: 2026-04-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f8a9b0c1d2e3"
down_revision: str | None = "e7f8a9b0c1d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "alert_silences",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column(
            "owner_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "monitor_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("monitors.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_alert_silences_owner_id", "alert_silences", ["owner_id"])
    op.create_index("ix_alert_silences_monitor_id", "alert_silences", ["monitor_id"])
    op.create_index("ix_alert_silences_window", "alert_silences", ["starts_at", "ends_at"])
    op.create_index(
        "ix_alert_silences_owner_monitor", "alert_silences", ["owner_id", "monitor_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_alert_silences_owner_monitor", table_name="alert_silences")
    op.drop_index("ix_alert_silences_window", table_name="alert_silences")
    op.drop_index("ix_alert_silences_monitor_id", table_name="alert_silences")
    op.drop_index("ix_alert_silences_owner_id", table_name="alert_silences")
    op.drop_table("alert_silences")
