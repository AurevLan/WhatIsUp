"""User model."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, Boolean, DateTime, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from whatisup.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from whatisup.models.alert import AlertChannel
    from whatisup.models.api_key import UserApiKey
    from whatisup.models.device_token import DeviceToken
    from whatisup.models.oncall import UserContact
    from whatisup.models.team import TeamMembership
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
    # Onboarding — null means wizard not completed yet
    onboarding_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    # OIDC subject identifier — set when account is linked to an OIDC provider.
    # Uniqueness lives in ``__table_args__`` under the name the base actually
    # carries (``uq_users_oidc_sub``); a `unique=True` here would instead expect
    # a unique *index* named ``ix_users_oidc_sub``.
    oidc_sub: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # User preference — IANA timezone (e.g. "Europe/Paris"). `None` means the
    # frontend falls back to the browser's resolved TZ. All timestamps remain
    # stored in UTC in the DB; this only controls display formatting.
    timezone: Mapped[str | None] = mapped_column(String(64), nullable=True, default=None)

    # 2FA TOTP — secret stored Fernet-encrypted at rest; a pending secret
    # (totp_enabled=False) becomes active only after the first valid code.
    totp_secret: Mapped[str | None] = mapped_column(Text, nullable=True)
    totp_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="false"
    )
    # Single-use recovery codes (bcrypt hashes); consumed entries are removed.
    totp_recovery_codes: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # Relationships
    alert_channels: Mapped[list[AlertChannel]] = relationship(
        "AlertChannel", back_populates="owner"
    )
    api_keys: Mapped[list[UserApiKey]] = relationship(
        "UserApiKey", back_populates="user", cascade="all, delete-orphan"
    )
    push_subscriptions: Mapped[list[WebPushSubscription]] = relationship(
        "WebPushSubscription", back_populates="user", cascade="all, delete-orphan"
    )
    device_tokens: Mapped[list[DeviceToken]] = relationship(
        "DeviceToken", back_populates="user", cascade="all, delete-orphan"
    )
    team_memberships: Mapped[list[TeamMembership]] = relationship(
        "TeamMembership", back_populates="user", cascade="all, delete-orphan"
    )
    contacts: Mapped[list[UserContact]] = relationship(
        "UserContact", back_populates="user", cascade="all, delete-orphan"
    )

    __table_args__ = (UniqueConstraint("oidc_sub", name="uq_users_oidc_sub"),)

    def __repr__(self) -> str:
        return f"<User {self.username!r}>"
