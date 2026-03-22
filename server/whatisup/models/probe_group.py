"""Probe group model — admin-created, grants probe visibility to users."""

from __future__ import annotations

from sqlalchemy import Column, ForeignKey, String, Table, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from whatisup.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

# Association: probe_group ↔ probe
probe_group_members = Table(
    "probe_group_members",
    Base.metadata,
    Column("probe_group_id", ForeignKey("probe_groups.id", ondelete="CASCADE"), primary_key=True),
    Column("probe_id", ForeignKey("probes.id", ondelete="CASCADE"), primary_key=True),
)

# Association: user ↔ probe_group (visibility access)
user_probe_group_access = Table(
    "user_probe_group_access",
    Base.metadata,
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("probe_group_id", ForeignKey("probe_groups.id", ondelete="CASCADE"), primary_key=True),
)


class ProbeGroup(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "probe_groups"

    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    probes: Mapped[list] = relationship("Probe", secondary=probe_group_members, lazy="selectin")
    users: Mapped[list] = relationship("User", secondary=user_probe_group_access, lazy="selectin")
