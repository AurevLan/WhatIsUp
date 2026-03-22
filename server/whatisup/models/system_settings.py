"""System-wide settings stored as a singleton DB row (id=1)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from whatisup.models.base import Base


class SystemSettings(Base):
    """Singleton row (id always 1) for runtime-configurable settings."""

    __tablename__ = "system_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    # OIDC / SSO — overrides env vars when the row exists
    oidc_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    oidc_issuer_url: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    oidc_client_id: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    # Fernet-encrypted at rest (same key as alert channel secrets)
    oidc_client_secret: Mapped[str] = mapped_column(Text, default="", nullable=False)
    oidc_redirect_uri: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    oidc_scopes: Mapped[str] = mapped_column(
        String(255), default="openid email profile", nullable=False
    )
    oidc_auto_provision: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
