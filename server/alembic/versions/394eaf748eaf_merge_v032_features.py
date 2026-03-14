"""merge_v032_features

Revision ID: 394eaf748eaf
Revises: a7b8c9d0e1f2, c9d0e1f2a3b4, e5f6a7b8c9d0
Create Date: 2026-03-13 20:38:41.497664

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '394eaf748eaf'
down_revision: Union[str, None] = ('a7b8c9d0e1f2', 'c9d0e1f2a3b4', 'e5f6a7b8c9d0')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
