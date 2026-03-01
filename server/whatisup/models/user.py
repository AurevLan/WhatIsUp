"""User model."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from whatisup.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from whatisup.models.tag import UserTagPermission
    from whatisup.models.alert import AlertChannel


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    username: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    hashed_password: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_superadmin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Relationships
    tag_permissions: Mapped[list["UserTagPermission"]] = relationship(
        "UserTagPermission", back_populates="user", cascade="all, delete-orphan"
    )
    alert_channels: Mapped[list["AlertChannel"]] = relationship(
        "AlertChannel", back_populates="owner"
    )

    def __repr__(self) -> str:
        return f"<User {self.username!r}>"
