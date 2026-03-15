"""User API key model."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from whatisup.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from whatisup.models.user import User


class UserApiKey(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Named API key for a user — an alternative to short-lived JWTs.

    The raw key (``wiu_u_<32 chars>``) is shown once at creation.
    Only the bcrypt hash is stored.  A short prefix is kept for display.
    """

    __tablename__ = "user_api_keys"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    key_hash: Mapped[str] = mapped_column(Text, nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(14), nullable=False)  # "wiu_u_XXXXXX" (12 chars)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)

    user: Mapped[User] = relationship("User", back_populates="api_keys")

    def __repr__(self) -> str:
        return f"<UserApiKey {self.name!r} prefix={self.key_prefix!r}>"
