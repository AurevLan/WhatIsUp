"""v0.3.1 — heartbeat check type

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-03-12 00:00:00.000000
"""
from __future__ import annotations
from alembic import op
import sqlalchemy as sa

revision = "c3d4e5f6a7b8"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("monitors", sa.Column("heartbeat_slug", sa.String(80), nullable=True, unique=True))
    op.add_column("monitors", sa.Column("heartbeat_interval_seconds", sa.Integer(), nullable=True))
    op.add_column("monitors", sa.Column("heartbeat_grace_seconds", sa.Integer(), nullable=True, server_default="60"))
    op.add_column("monitors", sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_monitors_heartbeat_slug", "monitors", ["heartbeat_slug"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_monitors_heartbeat_slug", table_name="monitors")
    op.drop_column("monitors", "last_heartbeat_at")
    op.drop_column("monitors", "heartbeat_grace_seconds")
    op.drop_column("monitors", "heartbeat_interval_seconds")
    op.drop_column("monitors", "heartbeat_slug")
