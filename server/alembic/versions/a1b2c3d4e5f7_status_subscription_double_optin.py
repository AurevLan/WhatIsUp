"""Double opt-in for status page subscriptions

Revision ID: a1b2c3d4e5f7
Revises: z2a3b4c5d6e7
Create Date: 2026-07-21

Ajoute `confirm_token` / `confirmed_at` à `status_subscriptions`.

Les lignes existantes sont marquées confirmées : elles ont été créées par
l'ancien endpoint, qui inscrivait sans confirmation. Les invalider
silencieusement priverait ces abonnés d'un service auquel ils se sont
inscrits, sans aucun moyen de le rétablir — le double opt-in ne s'applique
donc qu'aux inscriptions à venir.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f7"
down_revision: str | None = "z2a3b4c5d6e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "status_subscriptions",
        sa.Column("confirm_token", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "status_subscriptions",
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_unique_constraint(
        "uq_status_subscriptions_confirm_token",
        "status_subscriptions",
        ["confirm_token"],
    )
    # Cf. docstring : l'existant reste actif.
    op.execute(
        "UPDATE status_subscriptions SET confirmed_at = subscribed_at WHERE confirmed_at IS NULL"
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_status_subscriptions_confirm_token", "status_subscriptions", type_="unique"
    )
    op.drop_column("status_subscriptions", "confirmed_at")
    op.drop_column("status_subscriptions", "confirm_token")
