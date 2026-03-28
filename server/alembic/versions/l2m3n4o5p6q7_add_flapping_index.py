"""Add descending index on check_results(monitor_id, checked_at) for flapping detection

Revision ID: l2m3n4o5p6q7
Revises: k1l2m3n4o5p6
Create Date: 2026-03-28 22:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = 'l2m3n4o5p6q7'
down_revision: Union[str, None] = 'k1l2m3n4o5p6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX ix_check_results_monitor_checked "
        "ON check_results(monitor_id, checked_at DESC)"
    )


def downgrade() -> None:
    op.drop_index("ix_check_results_monitor_checked", table_name="check_results")
