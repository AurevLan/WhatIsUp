"""v0.3.0 — scenario check type

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-03-11 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "b2c3d4e5f6a7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add scenario columns to monitors
    op.add_column("monitors", sa.Column("scenario_steps", sa.JSON(), nullable=True))
    op.add_column("monitors", sa.Column("scenario_variables", sa.JSON(), nullable=True))

    # Add scenario_result to check_results
    op.add_column("check_results", sa.Column("scenario_result", sa.JSON(), nullable=True))

    # check_type is stored as String(20), no enum alteration needed


def downgrade() -> None:
    op.drop_column("monitors", "scenario_steps")
    op.drop_column("monitors", "scenario_variables")
    op.drop_column("check_results", "scenario_result")
