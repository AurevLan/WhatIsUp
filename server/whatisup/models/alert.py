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
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from whatisup.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

_JSON = JSON().with_variant(JSONB(), "postgresql")

if TYPE_CHECKING:
    from whatisup.models.incident import Incident
    from whatisup.models.monitor import Monitor
    from whatisup.models.oncall import EscalationPolicy
    from whatisup.models.user import User


class AlertChannelType(enum.StrEnum):
    email = "email"
    webhook = "webhook"
    telegram = "telegram"
    slack = "slack"
    pagerduty = "pagerduty"
    opsgenie = "opsgenie"
    signal = "signal"
    fcm = "fcm"  # Native push (Capacitor mobile app via Firebase Cloud Messaging)
    discord = "discord"
    mattermost = "mattermost"
    teams = "teams"


class AlertCondition(enum.StrEnum):
    """Plan cap v2, 6f — down from 10 to 4 members.

    ``condition`` is stored as a plain ``String`` (see ``AlertRule.condition``
    below), not a native PostgreSQL enum: the migration that shrank this enum
    (``p0q1r2s3t4u5``) needed to both retire six members and use two brand-new
    ones inside the same ``alembic upgrade`` run, and Postgres allows neither
    on a real enum type (labels can never be dropped, and a label added by
    ``ALTER TYPE ... ADD VALUE`` cannot be used until that transaction has
    committed — ``env.py`` runs every pending revision in one transaction).
    A plain string column sidesteps both restrictions for good.

    - ``availability`` — merges the old ``all_down``/``any_down`` (plan cap v2,
      F1-conditions): they were degenerate cases of the same question, "what
      fraction of probes must be down to page". See ``AlertRule.quorum_ratio``
      and ``services/conditions/availability.py``.
    - ``latency_anomaly`` — merges ``response_time_above`` (absolute),
      ``response_time_above_baseline`` (× 7-day rolling average) and
      ``anomaly_detection`` (z-score) (plan cap v2, F4): three answers to "is
      the latency abnormal", presented flat in the old picker with no way to
      tell which to pick. The sensitivity mode is inferred from which of
      ``threshold_value`` / ``baseline_factor`` / ``anomaly_zscore_threshold``
      is set — see ``services/conditions/latency.py``.
    - ``ssl_expiry`` / ``schema_drift`` — unchanged.

    Cut entirely (plan cap v2, C1): ``metric_above`` / ``metric_below`` /
    ``metric_absent`` — pushed-metric alerting. 0 rules, 0 points, 0 series on
    the real instance; replaced by an application endpoint that returns 500
    past its own threshold (monitored by a plain ``http`` check) or a pushed
    ``heartbeat`` for "agent is dead". Their removal is also what let
    ``Incident.alert_rule_id`` and ``IS_AVAILABILITY_INCIDENT`` disappear —
    see ``models/incident.py``.
    """

    availability = "availability"  # Quorum of probes down — see quorum_ratio
    ssl_expiry = "ssl_expiry"  # SSL cert expires within warn window
    latency_anomaly = "latency_anomaly"  # Abnormal response time — see sensitivity fields
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
    # signal: {"api_url": "...", "sender_number": "...", "recipients": [...]}
    config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # Optional Jinja-free template for webhook body (string.Template safe_substitute)
    webhook_template: Mapped[str | None] = mapped_column(Text, nullable=True)

    owner: Mapped[User] = relationship("User", back_populates="alert_channels")
    rules: Mapped[list[AlertRule]] = relationship(
        "AlertRule", secondary=alert_rule_channels, back_populates="channels"
    )
    alert_events: Mapped[list[AlertEvent]] = relationship("AlertEvent", back_populates="channel")


class AlertRule(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "alert_rules"

    owner_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    monitor_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("monitors.id", ondelete="CASCADE"), nullable=True, index=True
    )
    group_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("monitor_groups.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    # Plain string, not a native PostgreSQL enum — see AlertCondition's
    # docstring for why (plan cap v2, 6f / F1-conditions).
    condition: Mapped[str] = mapped_column(String(30), nullable=False)
    min_duration_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Latency (`latency_anomaly`), absolute mode: alert when response_time_ms
    # exceeds this fixed threshold. Also the sole numeric field for the
    # conditions that predate F4 (`ssl_expiry`'s warn-days override).
    threshold_value: Mapped[float | None] = mapped_column(sqlalchemy.Float, nullable=True)
    digest_minutes: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False, server_default="0"
    )
    # Storm protection: throttle if > storm_max_alerts sent in storm_window_seconds
    storm_window_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    storm_max_alerts: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Plan cap v2, F1-conditions — `availability`'s quorum setting: the
    # fraction (0, 1] of the monitor's probes that must be down at once for
    # the rule to fire. NULL (or any value < 1.0) behaves like the old
    # `any_down` — "at least one" — and 1.0 behaves like the old `all_down` —
    # "every probe". Only these two boundary values are meaningful today: the
    # incident only carries a binary `scope` (global vs. geographic), not a
    # live down-ratio, so an intermediate quorum cannot yet be evaluated
    # precisely — see AvailabilityHandler.decide(). Genuine intermediate
    # quorums are future work, gated on Incident tracking a real ratio.
    quorum_ratio: Mapped[float | None] = mapped_column(sqlalchemy.Float, nullable=True)
    # Latency (`latency_anomaly`), relative mode: alert when response_time >
    # baseline_factor × the 7-day rolling average.
    baseline_factor: Mapped[float | None] = mapped_column(sqlalchemy.Float, nullable=True)
    # Latency (`latency_anomaly`), statistical mode: z-score threshold (default 3.0).
    # F4 — the merged `latency_anomaly` condition infers its sensitivity mode
    # (absolute / relative / statistical) from which one of threshold_value /
    # baseline_factor / anomaly_zscore_threshold is set — see
    # schemas.alert.assert_latency_rule_is_fireable and
    # services/conditions/latency.py.
    anomaly_zscore_threshold: Mapped[float | None] = mapped_column(sqlalchemy.Float, nullable=True)
    # Business hours schedule: {timezone, days: [0-6], start/end: "HH:MM", offhours_suppress: bool}
    schedule: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Tag selector: list of tag names; rule fires for monitors carrying any matching tag.
    tag_selector: Mapped[list[str] | None] = mapped_column(_JSON, nullable=True)
    # Enable/disable without deleting the rule
    enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, server_default="true"
    )
    # V2-02-02 — Suppress dispatch when the incident's network_verdict is a
    # network partition (asn or geo). Defaults to False so existing rules keep
    # paging on transit-level outages until an operator opts in.
    suppress_on_network_partition: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="false"
    )
    # B-0 — optional escalation ladder. NULL keeps the historical behaviour
    # (fan out to `channels` once). Set, it hands the incident to the escalation
    # engine, which pages `levels` in order until an ack — plan cap v2 6e folded
    # the old standalone `renotify_after_minutes` into a one-rung, repeating
    # ladder, so "keep paging me until someone acks" is expressed here too.
    # ON DELETE SET NULL: deleting a policy must degrade the rule to the legacy
    # path, never cascade-delete the alert rule itself.
    escalation_policy_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("escalation_policies.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    monitor: Mapped[Monitor | None] = relationship(
        "Monitor", back_populates="alert_rules", foreign_keys=[monitor_id]
    )
    channels: Mapped[list[AlertChannel]] = relationship(
        "AlertChannel", secondary=alert_rule_channels, back_populates="rules"
    )
    escalation_policy: Mapped[EscalationPolicy | None] = relationship("EscalationPolicy")


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
