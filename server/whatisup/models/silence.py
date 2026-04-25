"""AlertSilence model — time-bounded suppression of alert dispatch (T1-01).

Distinct from MaintenanceWindow:
- MaintenanceWindow flags downtime as "expected" so it doesn't count against
  uptime SLA and may suppress per-monitor alerts inside the window.
- AlertSilence is a leaner, on-demand muting tool that the on-call uses to stop
  paging during a known-noisy event (cert expiry, storm, deploy) without
  affecting uptime numbers. It targets one monitor or every monitor of an
  owner; tag/team scoping is left as a follow-up.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from whatisup.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from whatisup.models.monitor import Monitor
    from whatisup.models.user import User


class AlertSilence(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "alert_silences"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    owner_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # NULL → applies to every monitor owned by ``owner_id``.
    monitor_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("monitors.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    owner: Mapped[User] = relationship("User", foreign_keys=[owner_id])
    monitor: Mapped[Monitor | None] = relationship("Monitor", foreign_keys=[monitor_id])

    __table_args__ = (
        Index("ix_alert_silences_window", "starts_at", "ends_at"),
        Index("ix_alert_silences_owner_monitor", "owner_id", "monitor_id"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        scope = f"monitor={self.monitor_id}" if self.monitor_id else "all monitors"
        return f"<AlertSilence {self.name!r} {scope} {self.starts_at}→{self.ends_at}>"
