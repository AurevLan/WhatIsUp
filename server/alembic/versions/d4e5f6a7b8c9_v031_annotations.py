"""v0.3.1 — monitor annotations

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-03-13 00:00:00.000000
"""
from __future__ import annotations
from alembic import op
import sqlalchemy as sa
import uuid as _uuid

revision = "d4e5f6a7b8c9"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "monitor_annotations",
        sa.Column("id", sa.UUID(), nullable=False, primary_key=True),
        sa.Column("monitor_id", sa.UUID(), sa.ForeignKey("monitors.id", ondelete="CASCADE"), nullable=False),
        sa.Column("content", sa.String(500), nullable=False),
        sa.Column("annotated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=True),
    )
    op.create_index("ix_annotations_monitor_id", "monitor_annotations", ["monitor_id"])


def downgrade() -> None:
    op.drop_index("ix_annotations_monitor_id", table_name="monitor_annotations")
    op.drop_table("monitor_annotations")
