"""CheckResult model — stores one HTTP check result per probe per monitor."""

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
    Float,
    ForeignKey,
    Index,
    Integer,
    Text,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from whatisup.models.base import Base

# Use JSONB on PostgreSQL (indexable), fall back to JSON on SQLite (tests)
_JSON = JSON().with_variant(JSONB(), "postgresql")

if TYPE_CHECKING:
    from whatisup.models.monitor import Monitor
    from whatisup.models.probe import Probe


class CheckStatus(enum.StrEnum):
    up = "up"
    down = "down"
    timeout = "timeout"
    error = "error"


class CheckResult(Base):
    __tablename__ = "check_results"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    monitor_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("monitors.id", ondelete="CASCADE"), nullable=False
    )
    probe_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("probes.id", ondelete="CASCADE"), nullable=True
    )
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # HTTP result
    status: Mapped[CheckStatus] = mapped_column(
        Enum(CheckStatus, name="check_status"), nullable=False
    )
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_time_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    redirect_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    final_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    # SSL result
    ssl_valid: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    ssl_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ssl_days_remaining: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Error info
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Scenario result
    scenario_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # DNS result — resolved values (replaces final_url abuse for DNS checks)
    dns_resolved_values: Mapped[list[str] | None] = mapped_column(_JSON, nullable=True)

    # HTTP waterfall timing (milliseconds)
    dns_resolve_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ttfb_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    download_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # API schema fingerprint (JSON structure hash sent by probe)
    schema_fingerprint: Mapped[str | None] = mapped_column(Text, nullable=True)

    # V2-02-03 — TLS chain audit (version, cipher, SAN, SCT, grade A-F)
    tls_audit: Mapped[dict | None] = mapped_column(_JSON, nullable=True)
    # V2-02-04 — DNS authoritative consistency (per-NS responses + drift flag)
    dns_consistency: Mapped[dict | None] = mapped_column(_JSON, nullable=True)

    # Relationships
    monitor: Mapped[Monitor] = relationship("Monitor", back_populates="check_results")
    probe: Mapped[Probe] = relationship("Probe", back_populates="check_results")

    __table_args__ = (
        Index("ix_cr_monitor_checked_at", "monitor_id", "checked_at"),
        Index("ix_cr_probe_checked_at", "probe_id", "checked_at"),
    )
