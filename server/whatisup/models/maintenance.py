"""Maintenance / suppression window model.

Plan cap v2, 6d — this table used to have a sibling, ``AlertSilence``
(``models/silence.py``, dropped in migration ``n8o9p0q1r2s3``): both were
"suppress alerts on a bounded time window" mechanisms, differing only in
whether the window counted as *planned* downtime (excluded from uptime,
eligible for the public status page) or a bare mute. Two tables, two
endpoints, two nav entries — and no way for the person opening the modal to
know which door to use. ``is_maintenance`` is now that one bit:

- ``True`` (default) — the pre-6d ``MaintenanceWindow`` behaviour:
  ``services.maintenance.is_in_maintenance`` suppresses incident creation
  entirely (so the downtime never enters the uptime calculation) and the
  window is eligible for ``api/v1/public.py`` (subject to the 5a
  ``public_message`` opt-in). Requires a ``monitor_id`` or ``group_id`` —
  "maintenance on nothing in particular" isn't a real scope.
- ``False`` — the pre-6d ``AlertSilence`` behaviour: the incident opens and
  counts normally; only alert *dispatch* is muted, via
  ``services.alert._is_silenced`` matching the channel's owner. No target at
  all (``monitor_id`` and ``group_id`` both ``NULL``) is legal here and means
  "every monitor I own" — the old ``AlertSilence`` catch-all.

Both flavours still stop escalade (``services.escalation._should_stop``)
through the same ``is_in_maintenance`` / dispatch-time silencing paths as
before; see CLAUDE.md § Astreinte et escalade.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from whatisup.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from whatisup.models.user import User


class MaintenanceWindow(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "maintenance_windows"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Cap v2, 5a — the only field of this model ever shown to an unauthenticated
    # visitor. `name`/`description` were written assuming they were internal and
    # must never be republished automatically (see api/v1/public.py). Nullable:
    # the operator opts in by writing something here, otherwise the status page
    # only announces the fact and window, never a reason.
    public_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    team_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("teams.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    monitor_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("monitors.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    group_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("monitor_groups.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Only meaningful when `group_id` is set — cascading suppression of
    # sibling alerts when the whole group is down during group-wide
    # maintenance (services.maintenance.is_group_maintenance_suppressed). A
    # monitor-scoped window suppresses incident creation unconditionally via
    # `is_in_maintenance`, regardless of this flag.
    suppress_alerts: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Cap v2, 6d — see module docstring. True = planned maintenance (excluded
    # from uptime, eligible for the public status page). False = a plain
    # alert silence (ex-AlertSilence): the incident opens and counts
    # normally, only dispatch is muted.
    is_maintenance: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    owner: Mapped[User] = relationship("User")
