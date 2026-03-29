"""Team and TeamMembership models."""

from __future__ import annotations

import enum
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from whatisup.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from whatisup.models.user import User


class TeamRole(enum.StrEnum):
    owner = "owner"
    admin = "admin"
    editor = "editor"
    viewer = "viewer"


class Team(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "teams"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(200), unique=True, index=True, nullable=False)

    # Relationships
    memberships: Mapped[list[TeamMembership]] = relationship(
        "TeamMembership", back_populates="team", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Team {self.name!r}>"


class TeamMembership(Base):
    __tablename__ = "team_memberships"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    team_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[TeamRole] = mapped_column(
        Enum(TeamRole, name="team_role"), nullable=False, default=TeamRole.viewer
    )

    user: Mapped[User] = relationship("User", back_populates="team_memberships")
    team: Mapped[Team] = relationship("Team", back_populates="memberships")

    __table_args__ = (
        Index("ix_tm_user_id", "user_id"),
        Index("ix_tm_team_id", "team_id"),
    )
