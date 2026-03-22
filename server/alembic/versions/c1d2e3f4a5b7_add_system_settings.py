"""add_system_settings

Revision ID: c1d2e3f4a5b7
Revises: b4c5d6e7f8a9
Create Date: 2026-03-22

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = 'c1d2e3f4a5b7'
down_revision = 'b4c5d6e7f8a9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'system_settings',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('oidc_enabled', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('oidc_issuer_url', sa.String(512), nullable=False, server_default=''),
        sa.Column('oidc_client_id', sa.String(255), nullable=False, server_default=''),
        sa.Column('oidc_client_secret', sa.Text(), nullable=False, server_default=''),
        sa.Column('oidc_redirect_uri', sa.String(512), nullable=False, server_default=''),
        sa.Column('oidc_scopes', sa.String(255), nullable=False, server_default='openid email profile'),
        sa.Column('oidc_auto_provision', sa.Boolean(), nullable=False, server_default='true'),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('system_settings')
