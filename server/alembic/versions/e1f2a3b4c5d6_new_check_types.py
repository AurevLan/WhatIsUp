"""Add UDP, SMTP, PING, domain_expiry check type fields

Revision ID: e1f2a3b4c5d6
Revises: b3c4d5e6f7a8
Create Date: 2026-03-16 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

revision = "e1f2a3b4c5d6"
down_revision = "b3c4d5e6f7a8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("monitors", sa.Column("udp_port", sa.Integer(), nullable=True))
    op.add_column(
        "monitors",
        sa.Column("smtp_port", sa.Integer(), nullable=True),
    )
    op.add_column(
        "monitors",
        sa.Column(
            "smtp_starttls",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )
    op.add_column(
        "monitors",
        sa.Column(
            "domain_expiry_warn_days",
            sa.Integer(),
            nullable=False,
            server_default="30",
        ),
    )


def downgrade() -> None:
    op.drop_column("monitors", "domain_expiry_warn_days")
    op.drop_column("monitors", "smtp_starttls")
    op.drop_column("monitors", "smtp_port")
    op.drop_column("monitors", "udp_port")
