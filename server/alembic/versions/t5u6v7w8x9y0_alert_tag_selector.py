"""Add AlertRule.tag_selector for tag-scoped alert rules.

Revision ID: t5u6v7w8x9y0
Revises: s4t5u6v7w8x9
Create Date: 2026-04-13 10:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "t5u6v7w8x9y0"
down_revision: Union[str, None] = "s4t5u6v7w8x9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "alert_rules",
        sa.Column(
            "tag_selector",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=True,
        ),
    )
    op.add_column(
        "alert_rules",
        sa.Column("owner_id", sa.Uuid(as_uuid=True), nullable=True),
    )
    op.create_index("ix_alert_rules_owner_id", "alert_rules", ["owner_id"])
    # Backfill owner_id from first channel's owner for existing rules
    op.execute(
        """
        UPDATE alert_rules AS r
        SET owner_id = (
            SELECT c.owner_id
            FROM alert_channels c
            JOIN alert_rule_channels arc ON arc.channel_id = c.id
            WHERE arc.rule_id = r.id
            LIMIT 1
        )
        WHERE r.owner_id IS NULL
        """
    )
    op.create_foreign_key(
        "fk_alert_rules_owner_id",
        "alert_rules",
        "users",
        ["owner_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("fk_alert_rules_owner_id", "alert_rules", type_="foreignkey")
    op.drop_index("ix_alert_rules_owner_id", table_name="alert_rules")
    op.drop_column("alert_rules", "owner_id")
    op.drop_column("alert_rules", "tag_selector")
