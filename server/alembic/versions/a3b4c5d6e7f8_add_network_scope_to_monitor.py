"""add network_scope to monitor

Revision ID: a3b4c5d6e7f8
Revises: 283efc2c973a
Create Date: 2026-03-21

"""
from alembic import op
import sqlalchemy as sa

revision = 'a3b4c5d6e7f8'
down_revision = '283efc2c973a'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('monitors', sa.Column(
        'network_scope', sa.String(20), nullable=False, server_default='all'
    ))


def downgrade() -> None:
    op.drop_column('monitors', 'network_scope')
