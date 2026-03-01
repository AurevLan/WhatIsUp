"""Incident model — aggregated outage detected across probes."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Index, Integer, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from whatisup.models.base import Base

if TYPE_CHECKING:
    from whatisup.models.alert import AlertEvent
    from whatisup.models.monitor import Monitor


class IncidentScope(str, enum.Enum):
    global_ = "global"      # All probes report down
    geographic = "geographic"  # Only some probes report down


class Incident(Base):
    __tablename__ = "incidents"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    monitor_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("monitors.id", ondelete="CASCADE"), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    scope: Mapped[IncidentScope] = mapped_column(
        Enum(IncidentScope, name="incident_scope"), nullable=False
    )
    affected_probe_ids: Mapped[list[str]] = mapped_column(
        JSON, default=list, nullable=False
    )

    # Relationships
    monitor: Mapped[Monitor] = relationship("Monitor", back_populates="incidents")
    alert_events: Mapped[list[AlertEvent]] = relationship(
        "AlertEvent", back_populates="incident", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_incidents_monitor_started", "monitor_id", "started_at"),
        Index("ix_incidents_resolved", "resolved_at"),
    )

    @property
    def is_resolved(self) -> bool:
        return self.resolved_at is not None
