"""dns_split_enabled_remove_consistency

Revision ID: 73c722e67eee
Revises: h1i2j3k4l5m6
Create Date: 2026-03-21 19:47:28.400737

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '73c722e67eee'
down_revision: Union[str, None] = 'h1i2j3k4l5m6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('monitors', sa.Column('dns_split_enabled', sa.Boolean(), server_default='false', nullable=False))
    op.add_column('monitors', sa.Column('dns_baseline_ips_internal', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True))
    op.add_column('monitors', sa.Column('dns_baseline_ips_external', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True))
    op.drop_column('monitors', 'dns_consistency_check')
    op.drop_column('monitors', 'dns_allow_split_horizon')


def downgrade() -> None:
    op.add_column('monitors', sa.Column('dns_allow_split_horizon', sa.BOOLEAN(), server_default=sa.text('false'), autoincrement=False, nullable=False))
    op.add_column('monitors', sa.Column('dns_consistency_check', sa.BOOLEAN(), server_default=sa.text('false'), autoincrement=False, nullable=False))
    op.drop_column('monitors', 'dns_baseline_ips_external')
    op.drop_column('monitors', 'dns_baseline_ips_internal')
    op.drop_column('monitors', 'dns_split_enabled')
