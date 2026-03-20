"""merge_heads_before_v033

Revision ID: g0h1i2j3k4l5
Revises: 394eaf748eaf, e3f4a5b6c7d8
Create Date: 2026-03-20 00:00:00.000000

"""

from __future__ import annotations

from typing import Union

from alembic import op

revision: str = "g0h1i2j3k4l5"
down_revision: Union[str, None] = ("394eaf748eaf", "e3f4a5b6c7d8")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
