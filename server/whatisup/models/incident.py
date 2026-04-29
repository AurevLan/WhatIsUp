"""Incident model — aggregated outage detected across probes."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, Boolean, DateTime, Enum, ForeignKey, Index, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from whatisup.models.base import Base

if TYPE_CHECKING:
    from whatisup.models.alert import AlertEvent
    from whatisup.models.incident_update import IncidentUpdate
    from whatisup.models.monitor import Monitor
    from whatisup.models.user import User


class IncidentScope(enum.StrEnum):
    global_ = "global"  # All probes report down
    geographic = "geographic"  # Only some probes report down


class IncidentGroup(Base):
    """Groups correlated incidents triggered by the same root cause (common probes)."""

    __tablename__ = "incident_groups"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    triggered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cause_probe_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="open", nullable=False)
    # Root cause: the monitor that went down first in this group
    root_cause_monitor_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("monitors.id", ondelete="SET NULL"), nullable=True
    )
    # Correlation source: probe | group | dependency | pattern
    correlation_type: Mapped[str | None] = mapped_column(String(30), nullable=True)

    incidents: Mapped[list[Incident]] = relationship("Incident", back_populates="group")
    root_cause_monitor: Mapped[Monitor | None] = relationship(
        "Monitor", foreign_keys=[root_cause_monitor_id]
    )

    __table_args__ = (Index("ix_incident_groups_status", "status"),)


class Incident(Base):
    __tablename__ = "incidents"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    monitor_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("monitors.id", ondelete="CASCADE"), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    scope: Mapped[IncidentScope] = mapped_column(
        Enum(IncidentScope, name="incident_scope"), nullable=False
    )
    affected_probe_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)

    # Set to True when a parent monitor is down and suppresses this incident's alerts
    dependency_suppressed: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="false"
    )

    # Acknowledgment — stops renotify; cleared on state change
    acked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    acked_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # Snooze (T1-04) — temporary alert suppression, unlike ack which is open-ended.
    # While snooze_until > now, renotify dispatches are skipped; once it expires the
    # incident re-arms. Any state change (resolve/unack) also clears it.
    snooze_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    # SLA: timestamp of the CheckResult that triggered the incident (for MTTD)
    first_failure_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # FK to correlation group (nullable — not all incidents are part of a group)
    group_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("incident_groups.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # V2-02-02 — Network intelligence verdict.
    # Computed from CheckResults of probes diversified by ASN/country to classify
    # whether the outage is a true service down or only visible through a network
    # partition. Values: service_down | network_partition_asn | network_partition_geo
    # | inconclusive. Recomputed every 5 min while the incident is open.
    network_verdict: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    network_verdict_computed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    monitor: Mapped[Monitor] = relationship("Monitor", back_populates="incidents")
    alert_events: Mapped[list[AlertEvent]] = relationship(
        "AlertEvent", back_populates="incident", cascade="all, delete-orphan"
    )
    group: Mapped[IncidentGroup | None] = relationship("IncidentGroup", back_populates="incidents")
    acked_by: Mapped[User | None] = relationship("User", foreign_keys=[acked_by_id])
    updates: Mapped[list[IncidentUpdate]] = relationship(
        "IncidentUpdate", back_populates="incident", cascade="all, delete-orphan",
        order_by="IncidentUpdate.created_at.asc()"
    )

    __table_args__ = (
        Index("ix_incidents_monitor_started", "monitor_id", "started_at"),
        Index("ix_incidents_resolved", "resolved_at"),
        # Partial unique index (PostgreSQL only) — created via Alembic migration
        # to prevent duplicate open incidents for the same monitor.
    )

    @property
    def is_resolved(self) -> bool:
        return self.resolved_at is not None
