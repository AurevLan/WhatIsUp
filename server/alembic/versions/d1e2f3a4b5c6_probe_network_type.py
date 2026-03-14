"""probe network_type

Revision ID: d1e2f3a4b5c6
Revises: 394eaf748eaf
Create Date: 2026-03-13 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

revision = 'd1e2f3a4b5c6'
down_revision = '394eaf748eaf'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE TYPE networktype AS ENUM ('internal', 'external')")
    op.add_column(
        'probes',
        sa.Column(
            'network_type',
            sa.Enum('internal', 'external', name='networktype'),
            nullable=False,
            server_default='external',
        ),
    )


def downgrade() -> None:
    op.drop_column('probes', 'network_type')
    op.execute("DROP TYPE networktype")
