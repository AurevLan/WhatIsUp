"""StatusAnnouncement — human-authored narration on a status page.

Plan cap V2, 5b. Deliberately **not** an `Incident`: `IS_AVAILABILITY_INCIDENT`
(in `models/incident.py`) treats every `Incident` as a probe-observed
availability event — it feeds SLA/downtime computation, the public page's
red/green state, and collides with `uq_incidents_monitor_open`. An
announcement is written by a human, not detected by a probe, and must never
touch any of that (see plan_cap_v2.md § 5b and CLAUDE.md "Deux familles
d'incidents"). It is rattached to a `MonitorGroup` (the page), not a
`Monitor`, and nothing in `services/stats.py` or `services/health.py` ever
reads it.

Reuses `IncidentUpdateStatus` for both the announcement's current state and
each update's status: the vocabulary status pages already show
(investigating/identified/monitoring/resolved) fits an announcement exactly
as well as an incident update, and a second enum with the same four values
would only be a twin to keep in sync.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from whatisup.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from whatisup.models.incident_update import IncidentUpdateStatus

if TYPE_CHECKING:
    from whatisup.models.monitor import MonitorGroup
    from whatisup.models.user import User


class StatusAnnouncement(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A human-written announcement shown on a group's public status page.

    Purely narrative: no stats/SLA/alert computation ever reads this table.
    """

    __tablename__ = "status_announcements"

    group_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("monitor_groups.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[IncidentUpdateStatus] = mapped_column(
        Enum(IncidentUpdateStatus, name="incident_update_status"), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # NULL while the announcement is active. Set by the "close" action —
    # never inferred from `status == resolved`, an operator may want to keep
    # narrating (further updates) after marking things resolved.
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    group: Mapped[MonitorGroup] = relationship("MonitorGroup")
    created_by: Mapped[User | None] = relationship("User")
    updates: Mapped[list[StatusAnnouncementUpdate]] = relationship(
        "StatusAnnouncementUpdate",
        back_populates="announcement",
        cascade="all, delete-orphan",
        order_by="StatusAnnouncementUpdate.created_at",
    )

    def __repr__(self) -> str:
        return f"<StatusAnnouncement {self.title!r}>"


class StatusAnnouncementUpdate(Base):
    """One entry in an announcement's timeline — modeled on `IncidentUpdate`,
    without touching `IncidentUpdate.incident_id` (a distinct FK/table)."""

    __tablename__ = "status_announcement_updates"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    announcement_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("status_announcements.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_by_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[IncidentUpdateStatus] = mapped_column(
        Enum(IncidentUpdateStatus, name="incident_update_status"), nullable=False
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)
    is_public: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, server_default="true"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    announcement: Mapped[StatusAnnouncement] = relationship(
        "StatusAnnouncement", back_populates="updates"
    )
    created_by: Mapped[User | None] = relationship("User")

    __table_args__ = (Index("ix_status_announcement_updates_announcement", "announcement_id"),)
