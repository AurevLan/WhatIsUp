"""v033 innovative features: waterfall timing, anomaly detection, schema drift,
business hours schedule, incident updates, monitor templates.

Revision ID: h1i2j3k4l5m6
Revises: g0h1i2j3k4l5
Create Date: 2026-03-20 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "h1i2j3k4l5m6"
down_revision = "g0h1i2j3k4l5"
branch_labels = None
depends_on = None

# Use JSONB on PostgreSQL, JSON otherwise
_JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    # ── check_results: waterfall timing + schema fingerprint ──────────────────
    op.add_column("check_results", sa.Column("dns_resolve_ms", sa.Integer(), nullable=True))
    op.add_column("check_results", sa.Column("ttfb_ms", sa.Integer(), nullable=True))
    op.add_column("check_results", sa.Column("download_ms", sa.Integer(), nullable=True))
    op.add_column("check_results", sa.Column("schema_fingerprint", sa.Text(), nullable=True))

    # ── alert_rules: anomaly z-score threshold + business hours schedule ──────
    op.add_column(
        "alert_rules",
        sa.Column("anomaly_zscore_threshold", sa.Float(), nullable=True),
    )
    op.add_column(
        "alert_rules",
        sa.Column("schedule", _JSON, nullable=True),
    )

    # ── alert_condition enum: add anomaly_detection + schema_drift ────────────
    op.execute("ALTER TYPE alert_condition ADD VALUE IF NOT EXISTS 'anomaly_detection'")
    op.execute("ALTER TYPE alert_condition ADD VALUE IF NOT EXISTS 'schema_drift'")

    # ── monitors: schema drift fields ─────────────────────────────────────────
    op.add_column(
        "monitors",
        sa.Column(
            "schema_drift_enabled",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )
    op.add_column("monitors", sa.Column("schema_baseline", sa.Text(), nullable=True))
    op.add_column(
        "monitors",
        sa.Column("schema_baseline_updated_at", sa.DateTime(timezone=True), nullable=True),
    )

    # ── incident_updates table ────────────────────────────────────────────────
    op.create_table(
        "incident_updates",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("incident_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_by_name", sa.String(255), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "investigating",
                "identified",
                "monitoring",
                "resolved",
                name="incident_update_status",
            ),
            nullable=False,
        ),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("is_public", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["incident_id"],
            ["incidents.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
    )
    op.create_index("ix_incident_updates_incident", "incident_updates", ["incident_id"])

    # ── monitor_templates table ───────────────────────────────────────────────
    op.create_table(
        "monitor_templates",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("variables", _JSON, nullable=True),
        sa.Column("monitor_config", _JSON, nullable=False),
        sa.Column(
            "is_public",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_monitor_templates_owner", "monitor_templates", ["owner_id"])


def downgrade() -> None:
    op.drop_index("ix_monitor_templates_owner", table_name="monitor_templates")
    op.drop_table("monitor_templates")

    op.drop_index("ix_incident_updates_incident", table_name="incident_updates")
    op.drop_table("incident_updates")
    op.execute("DROP TYPE IF EXISTS incident_update_status")

    op.drop_column("monitors", "schema_baseline_updated_at")
    op.drop_column("monitors", "schema_baseline")
    op.drop_column("monitors", "schema_drift_enabled")

    op.drop_column("alert_rules", "schedule")
    op.drop_column("alert_rules", "anomaly_zscore_threshold")

    op.drop_column("check_results", "schema_fingerprint")
    op.drop_column("check_results", "download_ms")
    op.drop_column("check_results", "ttfb_ms")
    op.drop_column("check_results", "dns_resolve_ms")
