"""Monitor and MonitorGroup models."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    Column,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
)
from sqlalchemy import Uuid
from sqlalchemy import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from whatisup.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from whatisup.models.tag import Tag
    from whatisup.models.result import CheckResult
    from whatisup.models.incident import Incident
    from whatisup.models.alert import AlertRule


# Many-to-many: monitor_groups <-> tags
monitor_group_tags = Table(
    "monitor_group_tags",
    Base.metadata,
    Column("group_id", Uuid(as_uuid=True), ForeignKey("monitor_groups.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", Uuid(as_uuid=True), ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)

# Many-to-many: monitors <-> tags
monitor_tags = Table(
    "monitor_tags",
    Base.metadata,
    Column("monitor_id", Uuid(as_uuid=True), ForeignKey("monitors.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", Uuid(as_uuid=True), ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)


class MonitorGroup(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "monitor_groups"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    public_slug: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True, index=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    tags: Mapped[list["Tag"]] = relationship("Tag", secondary=monitor_group_tags, lazy="selectin")
    monitors: Mapped[list["Monitor"]] = relationship("Monitor", back_populates="group")
    public_pages: Mapped[list["PublicPage"]] = relationship("PublicPage", back_populates="group")

    def __repr__(self) -> str:
        return f"<MonitorGroup {self.name!r}>"


class Monitor(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "monitors"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    group_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("monitor_groups.id", ondelete="SET NULL"), nullable=True, index=True
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Check configuration
    interval_seconds: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    follow_redirects: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    expected_status_codes: Mapped[list[int]] = mapped_column(JSON, default=lambda: [200], nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)

    # SSL monitoring
    ssl_check_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    ssl_expiry_warn_days: Mapped[int] = mapped_column(Integer, default=30, nullable=False)

    # Relationships
    tags: Mapped[list["Tag"]] = relationship("Tag", secondary=monitor_tags, lazy="selectin")
    group: Mapped["MonitorGroup | None"] = relationship("MonitorGroup", back_populates="monitors")
    check_results: Mapped[list["CheckResult"]] = relationship(
        "CheckResult", back_populates="monitor", cascade="all, delete-orphan"
    )
    incidents: Mapped[list["Incident"]] = relationship(
        "Incident", back_populates="monitor", cascade="all, delete-orphan"
    )
    alert_rules: Mapped[list["AlertRule"]] = relationship(
        "AlertRule", back_populates="monitor", foreign_keys="AlertRule.monitor_id"
    )

    __table_args__ = (
        Index("ix_monitors_enabled_owner", "enabled", "owner_id"),
    )

    def __repr__(self) -> str:
        return f"<Monitor {self.name!r} url={self.url!r}>"


class PublicPage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "public_pages"

    slug: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    group_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("monitor_groups.id", ondelete="SET NULL"), nullable=True, index=True
    )
    custom_domain: Mapped[str | None] = mapped_column(String(255), nullable=True)

    group: Mapped["MonitorGroup | None"] = relationship("MonitorGroup", back_populates="public_pages")
