"""v0.2 enrichment: check types, audit log, maintenance windows, alert improvements.

Revision ID: a1b2c3d4e5f6
Revises: 76f1c42af699
Create Date: 2026-03-10 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "76f1c42af699"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── Monitors: new check type fields ──────────────────────────────────────
    op.add_column("monitors", sa.Column("check_type", sa.String(20), nullable=False, server_default="http"))
    op.add_column("monitors", sa.Column("tcp_port", sa.Integer(), nullable=True))
    op.add_column("monitors", sa.Column("dns_record_type", sa.String(10), nullable=True))
    op.add_column("monitors", sa.Column("dns_expected_value", sa.String(512), nullable=True))
    op.add_column("monitors", sa.Column("keyword", sa.String(512), nullable=True))
    op.add_column("monitors", sa.Column("keyword_negate", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("monitors", sa.Column("expected_json_path", sa.String(512), nullable=True))
    op.add_column("monitors", sa.Column("expected_json_value", sa.String(512), nullable=True))

    # ── Alert channels: add 'slack' to enum ──────────────────────────────────
    op.execute("ALTER TYPE alert_channel_type ADD VALUE IF NOT EXISTS 'slack'")

    # ── Alert conditions: add perf-based conditions ───────────────────────────
    op.execute("ALTER TYPE alert_condition ADD VALUE IF NOT EXISTS 'response_time_above'")
    op.execute("ALTER TYPE alert_condition ADD VALUE IF NOT EXISTS 'uptime_below'")

    # ── Alert rules: renotify + threshold ────────────────────────────────────
    op.add_column("alert_rules", sa.Column("renotify_after_minutes", sa.Integer(), nullable=True))
    op.add_column("alert_rules", sa.Column("threshold_value", sa.Float(), nullable=True))

    # ── Audit log table ───────────────────────────────────────────────────────
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("user_email", sa.String(255), nullable=True),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("object_type", sa.String(100), nullable=False),
        sa.Column("object_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("object_name", sa.String(255), nullable=True),
        sa.Column("diff", sa.JSON(), nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
    )
    op.create_index("ix_audit_logs_timestamp", "audit_logs", ["timestamp"])
    op.create_index("ix_audit_logs_user_id", "audit_logs", ["user_id"])
    op.create_index("ix_audit_logs_object", "audit_logs", ["object_type", "object_id"])

    # ── Maintenance windows table ─────────────────────────────────────────────
    op.create_table(
        "maintenance_windows",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("owner_id", sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("monitor_id", sa.Uuid(as_uuid=True), sa.ForeignKey("monitors.id", ondelete="CASCADE"), nullable=True),
        sa.Column("group_id", sa.Uuid(as_uuid=True), sa.ForeignKey("monitor_groups.id", ondelete="CASCADE"), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("suppress_alerts", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_maintenance_windows_owner_id", "maintenance_windows", ["owner_id"])
    op.create_index("ix_maintenance_windows_monitor_id", "maintenance_windows", ["monitor_id"])
    op.create_index("ix_maintenance_windows_group_id", "maintenance_windows", ["group_id"])


def downgrade() -> None:
    op.drop_table("maintenance_windows")
    op.drop_table("audit_logs")
    op.drop_column("alert_rules", "threshold_value")
    op.drop_column("alert_rules", "renotify_after_minutes")
    op.drop_column("monitors", "expected_json_value")
    op.drop_column("monitors", "expected_json_path")
    op.drop_column("monitors", "keyword_negate")
    op.drop_column("monitors", "keyword")
    op.drop_column("monitors", "dns_expected_value")
    op.drop_column("monitors", "dns_record_type")
    op.drop_column("monitors", "tcp_port")
    op.drop_column("monitors", "check_type")
