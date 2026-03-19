"""DNS drift fields, composite monitor, probe_id nullable in check_results

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
Create Date: 2026-03-18 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "d2e3f4a5b6c7"
down_revision = "b2c3d4e5f6g7"
branch_labels = None
depends_on = None

# Use JSONB on PostgreSQL, fall back to JSON on SQLite (tests)
_JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    # --- check_results ---
    # 1. Add dns_resolved_values (proper field replacing final_url abuse for DNS)
    op.add_column(
        "check_results",
        sa.Column("dns_resolved_values", _JSON, nullable=True),
    )
    # 2. Make probe_id nullable (composite monitor synthetic checks have no probe)
    op.alter_column("check_results", "probe_id", nullable=True)

    # --- monitors: DNS drift fields ---
    op.add_column(
        "monitors",
        sa.Column("dns_baseline_ips", _JSON, nullable=True),
    )
    op.add_column(
        "monitors",
        sa.Column(
            "dns_drift_alert",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )
    op.add_column(
        "monitors",
        sa.Column(
            "dns_consistency_check",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )
    op.add_column(
        "monitors",
        sa.Column(
            "dns_allow_split_horizon",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )

    # --- monitors: composite aggregation rule ---
    op.add_column(
        "monitors",
        sa.Column("composite_aggregation", sa.String(20), nullable=True),
    )

    # --- composite_monitor_members ---
    op.create_table(
        "composite_monitor_members",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "composite_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("monitors.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "monitor_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("monitors.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("weight", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("role", sa.String(50), nullable=True),
    )
    op.create_index(
        "ix_cmm_composite_id", "composite_monitor_members", ["composite_id"]
    )
    op.create_index(
        "ix_cmm_monitor_id", "composite_monitor_members", ["monitor_id"]
    )
    op.create_unique_constraint(
        "uq_composite_member",
        "composite_monitor_members",
        ["composite_id", "monitor_id"],
    )


def downgrade() -> None:
    op.drop_table("composite_monitor_members")
    op.drop_column("monitors", "composite_aggregation")
    op.drop_column("monitors", "dns_allow_split_horizon")
    op.drop_column("monitors", "dns_consistency_check")
    op.drop_column("monitors", "dns_drift_alert")
    op.drop_column("monitors", "dns_baseline_ips")
    op.alter_column("check_results", "probe_id", nullable=False)
    op.drop_column("check_results", "dns_resolved_values")
