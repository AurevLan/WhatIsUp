"""merge_v0110

Revision ID: e358d5d5ca4d
Revises: f0a1b2c3d4e5, i1j2k3l4m5n6
Create Date: 2026-03-28 10:46:10.458775

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e358d5d5ca4d'
down_revision: Union[str, None] = ('f0a1b2c3d4e5', 'i1j2k3l4m5n6')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
