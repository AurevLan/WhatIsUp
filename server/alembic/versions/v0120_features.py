"""v0.12.0 features — auto_pause, status page customization, report schedule

Revision ID: k1l2m3n4o5p6
Revises: e358d5d5ca4d
Create Date: 2026-03-28 21:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'k1l2m3n4o5p6'
down_revision: Union[str, None] = 'e358d5d5ca4d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # F7: Auto-pause after N consecutive failures
    op.add_column('monitors', sa.Column('auto_pause_after', sa.Integer(), nullable=True))

    # F8: Status page customization
    op.add_column('monitor_groups', sa.Column('custom_logo_url', sa.String(500), nullable=True))
    op.add_column('monitor_groups', sa.Column('accent_color', sa.String(7), nullable=True))
    op.add_column('monitor_groups', sa.Column('announcement_banner', sa.Text(), nullable=True))

    # F6: Scheduled SLA reports
    op.add_column('monitor_groups', sa.Column('report_schedule', sa.String(20), nullable=True))
    op.add_column('monitor_groups', sa.Column('report_emails', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('monitor_groups', 'report_emails')
    op.drop_column('monitor_groups', 'report_schedule')
    op.drop_column('monitor_groups', 'announcement_banner')
    op.drop_column('monitor_groups', 'accent_color')
    op.drop_column('monitor_groups', 'custom_logo_url')
    op.drop_column('monitors', 'auto_pause_after')
