"""Alert channel, rule, and event models."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

import sqlalchemy
from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from whatisup.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from whatisup.models.incident import Incident
    from whatisup.models.monitor import Monitor
    from whatisup.models.user import User


class AlertChannelType(enum.StrEnum):
    email = "email"
    webhook = "webhook"
    telegram = "telegram"
    slack = "slack"
    pagerduty = "pagerduty"
    opsgenie = "opsgenie"


class AlertCondition(enum.StrEnum):
    all_down = "all_down"  # All probes report down (global outage)
    any_down = "any_down"  # Any probe reports down
    ssl_expiry = "ssl_expiry"  # SSL cert expires within warn window
    response_time_above = "response_time_above"
    uptime_below = "uptime_below"
    response_time_above_baseline = "response_time_above_baseline"  # > N× rolling 7-day avg
    anomaly_detection = "anomaly_detection"  # Z-score based anomaly on response time
    schema_drift = "schema_drift"  # JSON API structure changed vs baseline


class AlertEventStatus(enum.StrEnum):
    sent = "sent"
    failed = "failed"


# Many-to-many: alert_rules <-> alert_channels
alert_rule_channels = Table(
    "alert_rule_channels",
    Base.metadata,
    Column(
        "rule_id",
        Uuid(as_uuid=True),
        ForeignKey("alert_rules.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "channel_id",
        Uuid(as_uuid=True),
        ForeignKey("alert_channels.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class AlertChannel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "alert_channels"

    owner_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    team_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("teams.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[AlertChannelType] = mapped_column(
        Enum(AlertChannelType, name="alert_channel_type"), nullable=False
    )
    # JSON config — encrypted at application level before storage
    # email: {"to": ["a@b.com", ...]}
    # webhook: {"url": "...", "secret": "<fernet-encrypted>"}
    # telegram: {"bot_token": "<fernet-encrypted>", "chat_id": "..."}
    config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    owner: Mapped[User] = relationship("User", back_populates="alert_channels")
    rules: Mapped[list[AlertRule]] = relationship(
        "AlertRule", secondary=alert_rule_channels, back_populates="channels"
    )
    alert_events: Mapped[list[AlertEvent]] = relationship("AlertEvent", back_populates="channel")


class AlertRule(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "alert_rules"

    monitor_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("monitors.id", ondelete="CASCADE"), nullable=True, index=True
    )
    group_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("monitor_groups.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    condition: Mapped[AlertCondition] = mapped_column(
        Enum(AlertCondition, name="alert_condition"), nullable=False
    )
    min_duration_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    renotify_after_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    threshold_value: Mapped[float | None] = mapped_column(sqlalchemy.Float, nullable=True)
    digest_minutes: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False, server_default="0"
    )
    # Storm protection: throttle if > storm_max_alerts sent in storm_window_seconds
    storm_window_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    storm_max_alerts: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Baseline: alert when response_time > baseline_factor × 7-day rolling average
    baseline_factor: Mapped[float | None] = mapped_column(sqlalchemy.Float, nullable=True)
    # Anomaly detection: z-score threshold (default 3.0)
    anomaly_zscore_threshold: Mapped[float | None] = mapped_column(sqlalchemy.Float, nullable=True)
    # Business hours schedule: {timezone, days: [0-6], start/end: "HH:MM", offhours_suppress: bool}
    schedule: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Enable/disable without deleting the rule
    enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, server_default="true"
    )

    monitor: Mapped[Monitor | None] = relationship(
        "Monitor", back_populates="alert_rules", foreign_keys=[monitor_id]
    )
    channels: Mapped[list[AlertChannel]] = relationship(
        "AlertChannel", secondary=alert_rule_channels, back_populates="rules"
    )


class AlertEvent(Base):
    __tablename__ = "alert_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    incident_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False
    )
    channel_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("alert_channels.id", ondelete="CASCADE"), nullable=False
    )
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[AlertEventStatus] = mapped_column(
        Enum(AlertEventStatus, name="alert_event_status"), nullable=False
    )
    response_body: Mapped[str | None] = mapped_column(Text, nullable=True)

    incident: Mapped[Incident] = relationship("Incident", back_populates="alert_events")
    channel: Mapped[AlertChannel] = relationship("AlertChannel", back_populates="alert_events")

    __table_args__ = (
        Index("ix_alert_events_incident", "incident_id"),
        Index("ix_alert_events_sent_at", "sent_at"),
    )
