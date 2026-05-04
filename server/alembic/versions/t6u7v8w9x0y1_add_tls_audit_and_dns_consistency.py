"""V2-02-03 + V2-02-04 — Add tls_audit and dns_consistency JSONB columns.

Revision ID: t6u7v8w9x0y1
Revises: s5t6u7v8w9x0
Create Date: 2026-05-04 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "t6u7v8w9x0y1"
down_revision = "s5t6u7v8w9x0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "check_results",
        sa.Column("tls_audit", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "check_results",
        sa.Column("dns_consistency", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("check_results", "dns_consistency")
    op.drop_column("check_results", "tls_audit")
