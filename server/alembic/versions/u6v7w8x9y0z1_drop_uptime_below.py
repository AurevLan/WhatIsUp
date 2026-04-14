"""Drop the uptime_below alert condition — never implemented correctly.

The handler in services/incident.py didn't actually evaluate the rolling uptime
against the threshold — it just fired on every incident_opened, making it a
confusing duplicate of any_down. Removing it entirely.

Revision ID: u6v7w8x9y0z1
Revises: t5u6v7w8x9y0
Create Date: 2026-04-14
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "u6v7w8x9y0z1"
down_revision: str | None = "t5u6v7w8x9y0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DELETE FROM alert_rules WHERE condition = 'uptime_below'")


def downgrade() -> None:
    pass
