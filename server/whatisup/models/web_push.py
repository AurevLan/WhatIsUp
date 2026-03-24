"""WebPush subscription model."""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from whatisup.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class WebPushSubscription(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "web_push_subscriptions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Push service endpoint URL
    endpoint: Mapped[str] = mapped_column(Text, nullable=False)
    # Browser's public key (P-256 ECDH, base64url)
    p256dh: Mapped[str] = mapped_column(Text, nullable=False)
    # Shared auth secret (base64url)
    auth: Mapped[str] = mapped_column(Text, nullable=False)
    # Optional browser/device label
    user_agent: Mapped[str | None] = mapped_column(String(512))

    user: Mapped["User"] = relationship(back_populates="push_subscriptions")  # noqa: F821
