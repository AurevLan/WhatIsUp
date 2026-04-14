"""Create alert_matrix_templates table and seed system templates.

Revision ID: v7w8x9y0z1a2
Revises: u6v7w8x9y0z1
Create Date: 2026-04-14
"""

from __future__ import annotations

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

from whatisup.services.alert_matrix_templates import TEMPLATES

revision: str = "v7w8x9y0z1a2"
down_revision: str | None = "u6v7w8x9y0z1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


SYSTEM_NAMES = {
    "standard": ("Standard", "Défauts raisonnables : détection rapide, expiration SSL, dérive baseline."),
    "strict": ("Strict / Paging", "Configuration agressive pour services critiques. Panne globale immédiate + checks de latence."),
    "silent": ("Faible bruit", "Configuration tolérante pour dev/staging. Longue période de grâce, re-notifications rares."),
}


def upgrade() -> None:
    op.create_table(
        "alert_matrix_templates",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("check_type", sa.String(32), nullable=False),
        sa.Column("rows", JSONB().with_variant(sa.JSON(), "sqlite"), nullable=False),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.create_index("ix_alert_matrix_templates_check_type", "alert_matrix_templates", ["check_type"])

    # Seed system templates from current code definitions
    bind = op.get_bind()
    from uuid import uuid4

    for check_type, tpl_list in TEMPLATES.items():
        for tpl in tpl_list:
            tpl_id = tpl["id"]
            name, description = SYSTEM_NAMES.get(tpl_id, (tpl_id, None))
            bind.execute(
                sa.text(
                    "INSERT INTO alert_matrix_templates (id, name, description, check_type, rows, is_system) "
                    "VALUES (:id, :name, :description, :check_type, CAST(:rows AS JSONB), true)"
                ),
                {
                    "id": str(uuid4()),
                    "name": name,
                    "description": description,
                    "check_type": check_type,
                    "rows": json.dumps(tpl["rows"]),
                },
            )


def downgrade() -> None:
    op.drop_index("ix_alert_matrix_templates_check_type", table_name="alert_matrix_templates")
    op.drop_table("alert_matrix_templates")
