"""add oidc_sub to user

Revision ID: b4c5d6e7f8a9
Revises: a3b4c5d6e7f8
Create Date: 2026-03-21

"""
from alembic import op
import sqlalchemy as sa

revision = 'b4c5d6e7f8a9'
down_revision = 'a3b4c5d6e7f8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('users', sa.Column('oidc_sub', sa.String(512), nullable=True))
    op.create_unique_constraint('uq_users_oidc_sub', 'users', ['oidc_sub'])
    op.create_index('ix_users_oidc_sub', 'users', ['oidc_sub'])


def downgrade() -> None:
    op.drop_index('ix_users_oidc_sub', table_name='users')
    op.drop_constraint('uq_users_oidc_sub', 'users', type_='unique')
    op.drop_column('users', 'oidc_sub')
