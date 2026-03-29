"""Add teams table, team_memberships table, and team_id to ownable resources

Revision ID: m1n2o3p4q5r6
Revises: l2m3n4o5p6q7
Create Date: 2026-03-29 12:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "m1n2o3p4q5r6"
down_revision: Union[str, None] = "l2m3n4o5p6q7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Teams table ──────────────────────────────────────────────────────
    op.create_table(
        "teams",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("slug", sa.String(200), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_teams_id", "teams", ["id"])
    op.create_index("ix_teams_slug", "teams", ["slug"], unique=True)

    # ── Team memberships table ───────────────────────────────────────────
    op.create_table(
        "team_memberships",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("team_id", sa.Uuid(), nullable=False),
        sa.Column(
            "role",
            sa.Enum("owner", "admin", "editor", "viewer", name="team_role"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "team_id"),
    )
    op.create_index("ix_tm_user_id", "team_memberships", ["user_id"])
    op.create_index("ix_tm_team_id", "team_memberships", ["team_id"])

    # ── Add team_id FK to ownable resources ──────────────────────────────
    for table in ("monitors", "monitor_groups", "alert_channels", "maintenance_windows", "monitor_templates"):
        op.add_column(table, sa.Column("team_id", sa.Uuid(), nullable=True))
        op.create_index(f"ix_{table}_team_id", table, ["team_id"])
        op.create_foreign_key(
            f"fk_{table}_team_id",
            table,
            "teams",
            ["team_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    for table in ("monitor_templates", "maintenance_windows", "alert_channels", "monitor_groups", "monitors"):
        op.drop_constraint(f"fk_{table}_team_id", table, type_="foreignkey")
        op.drop_index(f"ix_{table}_team_id", table_name=table)
        op.drop_column(table, "team_id")

    op.drop_index("ix_tm_team_id", table_name="team_memberships")
    op.drop_index("ix_tm_user_id", table_name="team_memberships")
    op.drop_table("team_memberships")
    op.execute("DROP TYPE IF EXISTS team_role")

    op.drop_index("ix_teams_slug", table_name="teams")
    op.drop_index("ix_teams_id", table_name="teams")
    op.drop_table("teams")
