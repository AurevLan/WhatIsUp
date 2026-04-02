"""Incident improvements: ack, atomic creation, SLA metrics, digest persistence, batch correlation

Revision ID: p1q2r3s4t5u6
Revises: o1p2q3r4s5t6
Create Date: 2026-03-31 14:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "p1q2r3s4t5u6"
down_revision: Union[str, None] = "o1p2q3r4s5t6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -- Req 1: Incident acknowledgment
    op.add_column("incidents", sa.Column("acked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "incidents",
        sa.Column(
            "acked_by_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_incidents_acked_at", "incidents", ["acked_at"])

    # -- Req 3: Atomic incident creation (partial unique index)
    # First, close duplicate open incidents (keep the most recent one per monitor)
    op.execute(
        """
        UPDATE incidents SET resolved_at = now()
        WHERE resolved_at IS NULL
          AND id NOT IN (
            SELECT DISTINCT ON (monitor_id) id
            FROM incidents
            WHERE resolved_at IS NULL
            ORDER BY monitor_id, started_at DESC
          )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_incidents_monitor_open "
        "ON incidents (monitor_id) "
        "WHERE resolved_at IS NULL"
    )

    # -- Req 5: SLA metrics
    op.add_column(
        "incidents",
        sa.Column("first_failure_at", sa.DateTime(timezone=True), nullable=True),
    )

    # -- Req 6: Batch correlation — GIN index on affected_probe_ids
    # Column is JSON (not JSONB), so cast for GIN index
    op.execute(
        "CREATE INDEX ix_incidents_affected_probes_gin "
        "ON incidents USING GIN ((affected_probe_ids::jsonb) jsonb_path_ops)"
    )

    # -- Req 7: Digest persistence table
    op.create_table(
        "digest_windows",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "rule_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("alert_rules.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("flush_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("events_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("ctx_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_digest_windows_flush_at", "digest_windows", ["flush_at"])


def downgrade() -> None:
    op.drop_table("digest_windows")
    op.execute("DROP INDEX IF EXISTS ix_incidents_affected_probes_gin")
    op.drop_column("incidents", "first_failure_at")
    op.execute("DROP INDEX IF EXISTS uq_incidents_monitor_open")
    op.drop_index("ix_incidents_acked_at", "incidents")
    op.drop_column("incidents", "acked_by_id")
    op.drop_column("incidents", "acked_at")
