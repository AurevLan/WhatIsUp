"""add_web_push_subscriptions

Revision ID: f0a1b2c3d4e5
Revises: c1d2e3f4a5b7
Create Date: 2026-03-24

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = 'f0a1b2c3d4e5'
down_revision = 'c1d2e3f4a5b7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'web_push_subscriptions',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('endpoint', sa.Text(), nullable=False),
        sa.Column('p256dh', sa.Text(), nullable=False),
        sa.Column('auth', sa.Text(), nullable=False),
        sa.Column('user_agent', sa.String(512), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_web_push_subscriptions_user_id', 'web_push_subscriptions', ['user_id'])


def downgrade() -> None:
    op.drop_index('ix_web_push_subscriptions_user_id', 'web_push_subscriptions')
    op.drop_table('web_push_subscriptions')
