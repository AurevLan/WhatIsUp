"""Tag and RBAC permission models."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Column, Enum, ForeignKey, Index, String, Table, Text
from sqlalchemy import Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from whatisup.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from whatisup.models.user import User

import enum


class PermissionLevel(str, enum.Enum):
    view = "view"
    edit = "edit"
    admin = "admin"


class Tag(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "tags"

    name: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    color: Mapped[str | None] = mapped_column(String(7), nullable=True)  # hex #RRGGBB
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    user_permissions: Mapped[list["UserTagPermission"]] = relationship(
        "UserTagPermission", back_populates="tag", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Tag {self.name!r}>"


class UserTagPermission(Base):
    __tablename__ = "user_tag_permissions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True
    )
    permission: Mapped[PermissionLevel] = mapped_column(
        Enum(PermissionLevel, name="permission_level"), nullable=False
    )

    user: Mapped["User"] = relationship("User", back_populates="tag_permissions")
    tag: Mapped["Tag"] = relationship("Tag", back_populates="user_permissions")

    __table_args__ = (
        Index("ix_utp_user_id", "user_id"),
        Index("ix_utp_tag_id", "tag_id"),
    )
