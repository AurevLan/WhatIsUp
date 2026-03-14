"""Advanced HTTP assertions (body_regex, expected_headers, json_schema)

Revision ID: f6a7b8c9d0e1
Revises: d4e5f6a7b8c9
Create Date: 2026-03-13 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "f6a7b8c9d0e1"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("monitors", sa.Column("body_regex", sa.String(500), nullable=True))
    op.add_column("monitors", sa.Column("expected_headers", postgresql.JSONB(), nullable=True))
    op.add_column("monitors", sa.Column("json_schema", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("monitors", "json_schema")
    op.drop_column("monitors", "expected_headers")
    op.drop_column("monitors", "body_regex")
