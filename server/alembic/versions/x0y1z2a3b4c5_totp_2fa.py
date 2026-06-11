"""2FA TOTP — per-user secret (Fernet-encrypted), enabled flag, recovery codes.

Revision ID: x0y1z2a3b4c5
Revises: w9x0y1z2a3b4
Create Date: 2026-06-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "x0y1z2a3b4c5"
down_revision = "w9x0y1z2a3b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("totp_secret", sa.Text(), nullable=True))
    op.add_column(
        "users",
        sa.Column("totp_enabled", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column("users", sa.Column("totp_recovery_codes", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "totp_recovery_codes")
    op.drop_column("users", "totp_enabled")
    op.drop_column("users", "totp_secret")
