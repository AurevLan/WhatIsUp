"""StatusSubscription model — email subscriptions for public status pages."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from whatisup.models.base import Base


class StatusSubscription(Base):
    __tablename__ = "status_subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    group_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("monitor_groups.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    # Jeton de désinscription, présent dans chaque mail envoyé à l'abonné.
    token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    # Double opt-in : tant que `confirmed_at` est NULL, l'abonnement existe
    # mais ne reçoit aucune notification. Le jeton de confirmation est effacé
    # une fois consommé pour qu'il ne serve qu'une fois.
    confirm_token: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    subscribed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
