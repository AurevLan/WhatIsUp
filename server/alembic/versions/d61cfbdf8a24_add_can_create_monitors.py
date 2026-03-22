"""add_can_create_monitors

Revision ID: d61cfbdf8a24
Revises: 73c722e67eee
Create Date: 2026-03-21 21:12:00.647094

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'd61cfbdf8a24'
down_revision: Union[str, None] = '73c722e67eee'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('can_create_monitors', sa.Boolean(), server_default='false', nullable=False))


def downgrade() -> None:
    op.drop_column('users', 'can_create_monitors')
