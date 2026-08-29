"""Probe group model — admin-created, grants probe visibility to users."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Column, ForeignKey, Index, String, Table, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from whatisup.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from whatisup.models.probe import Probe
    from whatisup.models.user import User

# Association: probe_group ↔ probe
probe_group_members = Table(
    "probe_group_members",
    Base.metadata,
    Column("probe_group_id", ForeignKey("probe_groups.id", ondelete="CASCADE"), primary_key=True),
    Column("probe_id", ForeignKey("probes.id", ondelete="CASCADE"), primary_key=True),
    # `probe_id` is the *second* column of the composite PK, so the PK's own
    # btree does not serve a lookup keyed on `probe_id` alone — and that is
    # exactly the shape of three hot paths: every probe heartbeat (which
    # discovery sources target this probe's group?), `push_discovery`'s scope
    # check, and the admin probe view. Without this index each of those is a
    # full scan of the association table (audit finding, 2026-08).
    Index("ix_probe_group_members_probe_id", "probe_id"),
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

    # `Mapped[list["Probe"]]` — not bare `Mapped[list]` — matters here: without
    # the parameterized element type, SQLAlchemy's annotation-based collection
    # detection doesn't recognize this as a to-many relationship and infers
    # `uselist=False` despite `secondary=`, silently returning a single
    # arbitrary member instead of the whole collection whenever a group has
    # more than one (`schemas/probe_group.py::_to_list` was papering over
    # exactly this — real fix, not a second workaround, since plan E, E-2's
    # capability/election logic iterates the full collection).
    probes: Mapped[list[Probe]] = relationship(
        "Probe", secondary=probe_group_members, lazy="selectin"
    )
    users: Mapped[list[User]] = relationship(
        "User", secondary=user_probe_group_access, lazy="selectin"
    )
