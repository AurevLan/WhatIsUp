"""DeviceToken model — native push notification registration.

One row per (user, device) tuple. The Capacitor mobile app exchanges its FCM
registration token for a server-side row at first launch (and on every token
refresh). The encryption_key is generated server-side, returned to the device
once on registration, and used to wrap notification payloads end-to-end so
Google's FCM relay only sees opaque ciphertext.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from whatisup.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from whatisup.models.user import User


class DevicePlatform(enum.StrEnum):
    android = "android"
    ios = "ios"
    web = "web"


class DeviceToken(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "device_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # FCM (Android) or APNs (iOS) registration token. Unique across the table
    # so we never deliver the same alert twice to the same physical device.
    token: Mapped[str] = mapped_column(Text, nullable=False, unique=True, index=True)
    platform: Mapped[DevicePlatform] = mapped_column(
        SQLEnum(DevicePlatform, name="device_platform"),
        nullable=False,
        default=DevicePlatform.android,
    )
    # Fernet key (URL-safe base64) generated at registration time and returned
    # once. Used by the server to wrap notification payloads and by the device
    # to unwrap them. Rotating it requires re-registering the device.
    encryption_key: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship(back_populates="device_tokens")
