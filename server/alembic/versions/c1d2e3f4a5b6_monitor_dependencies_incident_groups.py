"""Add monitor_dependencies and incident_groups tables; group_id/dependency_suppressed on incidents

Revision ID: c1d2e3f4a5b6
Revises: e1f2a3b4c5d6
Create Date: 2026-03-17 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

revision = "c1d2e3f4a5b6"
down_revision = "e1f2a3b4c5d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # incident_groups
    op.create_table(
        "incident_groups",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("triggered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cause_probe_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
    )
    op.create_index("ix_incident_groups_status", "incident_groups", ["status"])

    # monitor_dependencies
    op.create_table(
        "monitor_dependencies",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "parent_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("monitors.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "child_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("monitors.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "suppress_on_parent_down",
            sa.Boolean(),
            nullable=False,
            server_default="true",
        ),
    )
    op.create_index("ix_dep_parent", "monitor_dependencies", ["parent_id"])
    op.create_index("ix_dep_child", "monitor_dependencies", ["child_id"])
    op.create_unique_constraint(
        "uq_monitor_dependency", "monitor_dependencies", ["parent_id", "child_id"]
    )

    # Add group_id FK and dependency_suppressed to incidents
    op.add_column(
        "incidents",
        sa.Column(
            "group_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("incident_groups.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_incidents_group_id", "incidents", ["group_id"])
    op.add_column(
        "incidents",
        sa.Column(
            "dependency_suppressed",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )


def downgrade() -> None:
    op.drop_column("incidents", "dependency_suppressed")
    op.drop_index("ix_incidents_group_id", "incidents")
    op.drop_column("incidents", "group_id")
    op.drop_table("monitor_dependencies")
    op.drop_table("incident_groups")
