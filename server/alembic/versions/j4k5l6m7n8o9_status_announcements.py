"""Add status_announcements + status_announcement_updates.

Cap v2, étape 5b — a human-authored announcement on a group's public status
page, decoupled from `Incident` (see models/status_announcement.py). Reuses
the existing `incident_update_status` PG enum type (created by the
`incident_updates` migration) rather than minting a twin — `create_type=False`
on both columns means this migration never re-issues `CREATE TYPE`.

Revision ID: j4k5l6m7n8o9
Revises: i3j4k5l6m7n8
Create Date: 2026-09-06
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "j4k5l6m7n8o9"
down_revision: str | None = "i3j4k5l6m7n8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _status_enum() -> postgresql.ENUM:
    return postgresql.ENUM(
        "investigating",
        "identified",
        "monitoring",
        "resolved",
        name="incident_update_status",
        create_type=False,
    )


def upgrade() -> None:
    op.create_table(
        "status_announcements",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "group_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("monitor_groups.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("status", _status_enum(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_status_announcements_group_id", "status_announcements", ["group_id"])

    op.create_table(
        "status_announcement_updates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "announcement_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("status_announcements.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_by_name", sa.String(length=255), nullable=True),
        sa.Column("status", _status_enum(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column(
            "is_public",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_status_announcement_updates_announcement",
        "status_announcement_updates",
        ["announcement_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_status_announcement_updates_announcement",
        table_name="status_announcement_updates",
    )
    op.drop_table("status_announcement_updates")
    op.drop_index("ix_status_announcements_group_id", table_name="status_announcements")
    op.drop_table("status_announcements")
    # `incident_update_status` is not dropped: still owned/used by
    # `incident_updates`.
