"""Global Health Engine M0 — monitor_health_states, slo_rules, incident triggers.

Revision ID: u7v8w9x0y1z2
Revises: t6u7v8w9x0y1
Create Date: 2026-05-05 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "u7v8w9x0y1z2"
down_revision = "t6u7v8w9x0y1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "monitors",
        sa.Column(
            "health_engine_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    slo_rule_type = postgresql.ENUM(
        "quorum_down",
        "quorum_slow",
        "burn_rate",
        name="slo_rule_type",
        create_type=False,
    )
    slo_rule_type.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "slo_rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "monitor_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("monitors.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("rule_type", slo_rule_type, nullable=False),
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("quorum_ratio", sa.Float(), nullable=True),
        sa.Column("window_seconds", sa.Integer(), nullable=True),
        sa.Column("p95_threshold_ms", sa.Integer(), nullable=True),
        sa.Column("slo_target", sa.Float(), nullable=True),
        sa.Column("burn_factor", sa.Float(), nullable=True),
        sa.Column(
            "min_probes",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column(
            "cooldown_seconds",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("60"),
        ),
    )
    op.create_index(
        "ix_slo_rules_monitor_enabled",
        "slo_rules",
        ["monitor_id", "enabled"],
    )

    op.create_table(
        "monitor_health_states",
        sa.Column(
            "monitor_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("monitors.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "probes_state",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("p50_5m", sa.Float(), nullable=True),
        sa.Column("p95_5m", sa.Float(), nullable=True),
        sa.Column("p99_5m", sa.Float(), nullable=True),
        sa.Column(
            "sample_count_5m",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("tdigest_1h", sa.LargeBinary(), nullable=True),
        sa.Column("tdigest_6h", sa.LargeBinary(), nullable=True),
        sa.Column("tdigest_24h", sa.LargeBinary(), nullable=True),
        sa.Column(
            "quorum_down_ratio",
            sa.Float(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("current_scope", sa.String(length=20), nullable=True),
        sa.Column(
            "probe_health",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )

    op.add_column(
        "incidents",
        sa.Column(
            "slo_rule_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("slo_rules.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "incidents",
        sa.Column(
            "trigger_kind",
            sa.String(length=30),
            nullable=False,
            server_default=sa.text("'legacy'"),
        ),
    )
    op.create_index("ix_incidents_slo_rule_id", "incidents", ["slo_rule_id"])


def downgrade() -> None:
    op.drop_index("ix_incidents_slo_rule_id", table_name="incidents")
    op.drop_column("incidents", "trigger_kind")
    op.drop_column("incidents", "slo_rule_id")

    op.drop_table("monitor_health_states")

    op.drop_index("ix_slo_rules_monitor_enabled", table_name="slo_rules")
    op.drop_table("slo_rules")
    postgresql.ENUM(name="slo_rule_type").drop(op.get_bind(), checkfirst=True)

    op.drop_column("monitors", "health_engine_enabled")
