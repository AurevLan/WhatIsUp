"""Drop monitor_templates table (plan cap v2, étape 6a).

Templates never earned their keep: ``monitor_templates`` has 0 rows on the
real instance, yet the feature cost a permanent nav entry seen by every user.
Retired in favour of a "Duplicate" action on the monitor detail page, which
covers the actual gesture templates served without the extra concept.

``downgrade()`` recreates the table exactly as it stood at ``head`` — columns,
both indexes on ``owner_id`` (the redundant pair predates this migration and
isn't this migration's job to clean up), the ``team_id`` FK added by
``m1n2o3p4q5r6``, and the JSON/JSONB variant used by the ORM column type.

Revision ID: af00103e3c8a
Revises: k5l6m7n8o9p0
Create Date: 2026-09-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "af00103e3c8a"
down_revision: str | None = "k5l6m7n8o9p0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.drop_index("ix_monitor_templates_team_id", table_name="monitor_templates")
    op.drop_index("ix_monitor_templates_owner_id", table_name="monitor_templates")
    op.drop_index("ix_monitor_templates_owner", table_name="monitor_templates")
    op.drop_table("monitor_templates")


def downgrade() -> None:
    op.create_table(
        "monitor_templates",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("team_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("variables", _JSON, nullable=True),
        sa.Column("monitor_config", _JSON, nullable=False),
        sa.Column("is_public", sa.Boolean(), nullable=False, server_default="false"),
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
        sa.ForeignKeyConstraint(
            ["team_id"], ["teams.id"], name="fk_monitor_templates_team_id", ondelete="SET NULL"
        ),
    )
    op.create_index("ix_monitor_templates_owner", "monitor_templates", ["owner_id"])
    op.create_index(
        "ix_monitor_templates_owner_id", "monitor_templates", ["owner_id"], unique=False
    )
    op.create_index("ix_monitor_templates_team_id", "monitor_templates", ["team_id"], unique=False)
