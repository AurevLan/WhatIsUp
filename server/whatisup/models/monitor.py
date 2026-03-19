"""Monitor and MonitorGroup models."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from whatisup.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

# Use JSONB on PostgreSQL (indexable), fall back to JSON on SQLite (tests)
_JSON = JSON().with_variant(JSONB(), "postgresql")


class CheckType(enum.StrEnum):
    http = "http"
    tcp = "tcp"
    udp = "udp"
    dns = "dns"
    keyword = "keyword"
    json_path = "json_path"
    scenario = "scenario"
    heartbeat = "heartbeat"
    smtp = "smtp"
    ping = "ping"
    domain_expiry = "domain_expiry"
    composite = "composite"


if TYPE_CHECKING:
    from whatisup.models.alert import AlertRule
    from whatisup.models.incident import Incident
    from whatisup.models.result import CheckResult
    from whatisup.models.tag import Tag


class MonitorDependency(Base):
    """Parent → child dependency: when parent is down, suppress child incidents."""

    __tablename__ = "monitor_dependencies"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    parent_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("monitors.id", ondelete="CASCADE"),
        nullable=False,
    )
    child_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("monitors.id", ondelete="CASCADE"),
        nullable=False,
    )
    suppress_on_parent_down: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )

    parent: Mapped[Monitor] = relationship(
        "Monitor", foreign_keys=[parent_id], back_populates="child_dependencies"
    )
    child: Mapped[Monitor] = relationship(
        "Monitor", foreign_keys=[child_id], back_populates="parent_dependencies"
    )

    __table_args__ = (
        UniqueConstraint("parent_id", "child_id", name="uq_monitor_dependency"),
        Index("ix_dep_parent", "parent_id"),
        Index("ix_dep_child", "child_id"),
    )


class CompositeMonitorMember(Base):
    """Links a composite monitor to one of its source monitors."""

    __tablename__ = "composite_monitor_members"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    composite_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("monitors.id", ondelete="CASCADE"),
        nullable=False,
    )
    monitor_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("monitors.id", ondelete="CASCADE"),
        nullable=False,
    )
    weight: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    role: Mapped[str | None] = mapped_column(String(50), nullable=True)

    composite: Mapped[Monitor] = relationship(
        "Monitor", foreign_keys=[composite_id], back_populates="composite_members"
    )
    member: Mapped[Monitor] = relationship(
        "Monitor", foreign_keys=[monitor_id], back_populates="composite_memberships"
    )

    __table_args__ = (
        UniqueConstraint("composite_id", "monitor_id", name="uq_composite_member"),
        Index("ix_cmm_composite_id", "composite_id"),
        Index("ix_cmm_monitor_id", "monitor_id"),
    )


# Many-to-many: monitor_groups <-> tags
monitor_group_tags = Table(
    "monitor_group_tags",
    Base.metadata,
    Column(
        "group_id",
        Uuid(as_uuid=True),
        ForeignKey("monitor_groups.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "tag_id", Uuid(as_uuid=True), ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True
    ),
)

# Many-to-many: monitors <-> tags
monitor_tags = Table(
    "monitor_tags",
    Base.metadata,
    Column(
        "monitor_id",
        Uuid(as_uuid=True),
        ForeignKey("monitors.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "tag_id", Uuid(as_uuid=True), ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True
    ),
)


class MonitorGroup(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "monitor_groups"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    public_slug: Mapped[str | None] = mapped_column(
        String(100), unique=True, nullable=True, index=True
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    tags: Mapped[list[Tag]] = relationship("Tag", secondary=monitor_group_tags, lazy="selectin")
    monitors: Mapped[list[Monitor]] = relationship("Monitor", back_populates="group")
    public_pages: Mapped[list[PublicPage]] = relationship("PublicPage", back_populates="group")

    def __repr__(self) -> str:
        return f"<MonitorGroup {self.name!r}>"


class Monitor(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "monitors"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    group_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("monitor_groups.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Check configuration
    interval_seconds: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    follow_redirects: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    expected_status_codes: Mapped[list[int]] = mapped_column(
        JSON, default=lambda: [200], nullable=False
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)

    # SSL monitoring
    ssl_check_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    ssl_expiry_warn_days: Mapped[int] = mapped_column(Integer, default=30, nullable=False)

    # Check type
    check_type: Mapped[str] = mapped_column(String(20), default="http", nullable=False)

    # TCP checks
    tcp_port: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # UDP checks
    udp_port: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # SMTP checks
    smtp_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    smtp_starttls: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="false"
    )

    # Domain expiry checks
    domain_expiry_warn_days: Mapped[int] = mapped_column(
        Integer, default=30, nullable=False, server_default="30"
    )

    # DNS checks
    dns_record_type: Mapped[str | None] = mapped_column(
        String(10), nullable=True
    )  # A, AAAA, CNAME, MX, TXT
    dns_expected_value: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # DNS drift / cross-probe consistency
    dns_baseline_ips: Mapped[list[str] | None] = mapped_column(_JSON, nullable=True)
    dns_drift_alert: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="false"
    )
    dns_consistency_check: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="false"
    )
    dns_allow_split_horizon: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="false"
    )

    # Composite monitor aggregation rule
    composite_aggregation: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )  # majority_up | all_up | any_up | weighted_up

    # Keyword / body checks
    keyword: Mapped[str | None] = mapped_column(String(512), nullable=True)
    keyword_negate: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # JSON path checks
    expected_json_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    expected_json_value: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # Scenario checks
    scenario_steps: Mapped[list | None] = mapped_column(JSON, nullable=True)
    scenario_variables: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # Advanced HTTP assertions
    body_regex: Mapped[str | None] = mapped_column(String(500), nullable=True)
    expected_headers: Mapped[dict | None] = mapped_column(_JSON, nullable=True)
    json_schema: Mapped[dict | None] = mapped_column(_JSON, nullable=True)

    # SLO / Error Budget
    slo_target: Mapped[float | None] = mapped_column(Float, nullable=True)  # ex: 99.9
    slo_window_days: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="30", default=30
    )

    # Flapping detection — per-monitor thresholds (override global defaults)
    flap_threshold: Mapped[int] = mapped_column(
        Integer, default=5, nullable=False, server_default="5"
    )
    flap_window_minutes: Mapped[int] = mapped_column(
        Integer, default=10, nullable=False, server_default="10"
    )

    # Heartbeat / cron check type
    heartbeat_slug: Mapped[str | None] = mapped_column(String(80), nullable=True, unique=True)
    heartbeat_interval_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    heartbeat_grace_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="60", default=60
    )
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    tags: Mapped[list[Tag]] = relationship("Tag", secondary=monitor_tags, lazy="selectin")
    group: Mapped[MonitorGroup | None] = relationship("MonitorGroup", back_populates="monitors")
    check_results: Mapped[list[CheckResult]] = relationship(
        "CheckResult", back_populates="monitor", cascade="all, delete-orphan"
    )
    incidents: Mapped[list[Incident]] = relationship(
        "Incident", back_populates="monitor", cascade="all, delete-orphan"
    )
    alert_rules: Mapped[list[AlertRule]] = relationship(
        "AlertRule", back_populates="monitor", foreign_keys="AlertRule.monitor_id"
    )
    # Dependencies: parent monitors (this depends on) and child monitors (depend on this)
    parent_dependencies: Mapped[list[MonitorDependency]] = relationship(
        "MonitorDependency",
        foreign_keys="MonitorDependency.child_id",
        back_populates="child",
        cascade="all, delete-orphan",
    )
    child_dependencies: Mapped[list[MonitorDependency]] = relationship(
        "MonitorDependency",
        foreign_keys="MonitorDependency.parent_id",
        back_populates="parent",
        cascade="all, delete-orphan",
    )

    # Composite monitor: members this monitor aggregates
    composite_members: Mapped[list[CompositeMonitorMember]] = relationship(
        "CompositeMonitorMember",
        foreign_keys="CompositeMonitorMember.composite_id",
        back_populates="composite",
        cascade="all, delete-orphan",
    )
    # Composite monitor: composites this monitor belongs to (as a member)
    composite_memberships: Mapped[list[CompositeMonitorMember]] = relationship(
        "CompositeMonitorMember",
        foreign_keys="CompositeMonitorMember.monitor_id",
        back_populates="member",
        cascade="all, delete-orphan",
    )

    __table_args__ = (Index("ix_monitors_enabled_owner", "enabled", "owner_id"),)

    def __repr__(self) -> str:
        return f"<Monitor {self.name!r} url={self.url!r}>"


class PublicPage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "public_pages"

    slug: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    group_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("monitor_groups.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    custom_domain: Mapped[str | None] = mapped_column(String(255), nullable=True)

    group: Mapped[MonitorGroup | None] = relationship("MonitorGroup", back_populates="public_pages")
