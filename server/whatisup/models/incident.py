"""Incident model — aggregated outage detected across probes."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Uuid,
    text,
)
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

    # Global Health Engine — null on incidents created by the legacy pipeline.
    slo_rule_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("slo_rules.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    trigger_kind: Mapped[str] = mapped_column(
        String(30), nullable=False, default="legacy", server_default="legacy"
    )

    # Plan V2, C-4 — the discriminator between the two incident families.
    #   NULL     → availability incident (a probe, the heartbeat or the health
    #              engine says the monitor is in trouble)
    #   NOT NULL → metric incident, owned by that alert rule
    # It exists because the alert pipeline is incident-anchored while a pushed
    # metric has no CheckResult: a metric alert must open an incident, and an
    # undiscriminated one would be picked up by ``process_check_result`` as *the*
    # open incident and mask a real outage. Every query that means "is this
    # monitor currently down?" must therefore filter on ``alert_rule_id IS NULL``
    # — the partial unique indexes below encode the same split.
    alert_rule_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("alert_rules.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    # Relationships
    monitor: Mapped[Monitor] = relationship("Monitor", back_populates="incidents")
    alert_events: Mapped[list[AlertEvent]] = relationship(
        "AlertEvent", back_populates="incident", cascade="all, delete-orphan"
    )
    group: Mapped[IncidentGroup | None] = relationship("IncidentGroup", back_populates="incidents")
    acked_by: Mapped[User | None] = relationship("User", foreign_keys=[acked_by_id])
    updates: Mapped[list[IncidentUpdate]] = relationship(
        "IncidentUpdate",
        back_populates="incident",
        cascade="all, delete-orphan",
        order_by="IncidentUpdate.created_at.asc()",
    )

    __table_args__ = (
        Index("ix_incidents_monitor_started", "monitor_id", "started_at"),
        Index("ix_incidents_resolved", "resolved_at"),
        # The two indexes below are PostgreSQL-only and were previously created
        # by migration alone. Undeclared, they were invisible to
        # ``autogenerate``, which proposed dropping them on every run — the
        # partial unique one being the only thing preventing duplicate open
        # incidents for a monitor. ``ddl_if`` keeps them out of the SQLite
        # ``create_all`` used by the tests while leaving them in the metadata
        # that Alembic compares against.
        Index(
            "uq_incidents_monitor_open",
            "monitor_id",
            unique=True,
            postgresql_where=text("resolved_at IS NULL AND alert_rule_id IS NULL"),
        ).ddl_if(dialect="postgresql"),
        # C-4 — the metric half of the same invariant. One open incident per
        # (monitor, rule) instead of per monitor: two rules watching two
        # different metrics on the same monitor must be able to fire at once,
        # which is exactly what the index above forbids for availability.
        Index(
            "uq_incidents_monitor_rule_open",
            "monitor_id",
            "alert_rule_id",
            unique=True,
            postgresql_where=text("resolved_at IS NULL AND alert_rule_id IS NOT NULL"),
        ).ddl_if(dialect="postgresql"),
        # The operator class goes in ``postgresql_ops``, not inline in the
        # expression: Alembic gives up on comparing an expression that carries
        # one, and an index it cannot compare is an index it cannot vouch for.
        Index(
            "ix_incidents_affected_probes_gin",
            text("((affected_probe_ids)::jsonb)"),
            postgresql_using="gin",
            postgresql_ops={"((affected_probe_ids)::jsonb)": "jsonb_path_ops"},
        ).ddl_if(dialect="postgresql"),
    )

    @property
    def is_resolved(self) -> bool:
        return self.resolved_at is not None

    @property
    def is_metric_incident(self) -> bool:
        """True when this incident is a pushed-metric breach, not an outage."""
        return self.alert_rule_id is not None


#: Filter clause selecting **availability** incidents only (C-4).
#:
#: Carry it in every query that answers "is this monitor down?", "how much
#: downtime did it have?" or "which incident is currently open for it?". Without
#: it a metric incident is indistinguishable from an outage: at best it inflates
#: downtime and lights the status page red, at worst a ``scalar_one_or_none()``
#: raises ``MultipleResultsFound`` or hands the check pipeline the wrong row and
#: a real outage opens no incident at all.
#:
#: Deliberately *absent* from the user-facing incident lists, the ack/snooze
#: endpoints and the renotify loop — metric incidents are meant to show up and be
#: actionable there.
IS_AVAILABILITY_INCIDENT = Incident.alert_rule_id.is_(None)
