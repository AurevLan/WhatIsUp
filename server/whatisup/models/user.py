"""User model."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from whatisup.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from whatisup.models.alert import AlertChannel
    from whatisup.models.api_key import UserApiKey
    from whatisup.models.tag import UserTagPermission
    from whatisup.models.web_push import WebPushSubscription


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    username: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    hashed_password: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_superadmin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    can_create_monitors: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="false"
    )
    # OIDC subject identifier — set when account is linked to an OIDC provider
    oidc_sub: Mapped[str | None] = mapped_column(
        String(512), unique=True, nullable=True, index=True
    )

    # Relationships
    tag_permissions: Mapped[list[UserTagPermission]] = relationship(
        "UserTagPermission", back_populates="user", cascade="all, delete-orphan"
    )
    alert_channels: Mapped[list[AlertChannel]] = relationship(
        "AlertChannel", back_populates="owner"
    )
    api_keys: Mapped[list[UserApiKey]] = relationship(
        "UserApiKey", back_populates="user", cascade="all, delete-orphan"
    )
    push_subscriptions: Mapped[list[WebPushSubscription]] = relationship(
        "WebPushSubscription", back_populates="user", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<User {self.username!r}>"
