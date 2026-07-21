"""Scopes on user API keys

Revision ID: b2c3d4e5f6a8
Revises: a1b2c3d4e5f7
Create Date: 2026-07-21

Ajoute `scopes` à `user_api_keys`.

Les clés existantes reçoivent `["read", "write"]` : elles ont été émises avec
les pleins pouvoirs et sont déjà en circulation. Les restreindre ici casserait
silencieusement les intégrations en place — la restriction est donc un choix
explicite à la création, jamais une conséquence de la migration.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b2c3d4e5f6a8"
down_revision: str | None = "a1b2c3d4e5f7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "user_api_keys",
        sa.Column("scopes", sa.JSON(), nullable=True),
    )
    # Cf. docstring : l'existant garde ses droits.
    op.execute("""UPDATE user_api_keys SET scopes = '["read", "write"]' WHERE scopes IS NULL""")
    op.alter_column("user_api_keys", "scopes", nullable=False)


def downgrade() -> None:
    op.drop_column("user_api_keys", "scopes")
