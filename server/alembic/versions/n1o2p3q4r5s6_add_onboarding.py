"""Add onboarding_completed_at to users

Revision ID: n1o2p3q4r5s6
Revises: m1n2o3p4q5r6
Create Date: 2026-03-29 14:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "n1o2p3q4r5s6"
down_revision: Union[str, None] = "m1n2o3p4q5r6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("onboarding_completed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "onboarding_completed_at")
