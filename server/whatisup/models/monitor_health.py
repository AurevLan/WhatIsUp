"""Monitor health state + SLO rule models — V2 Global Health Engine (foundation M0)."""

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
    LargeBinary,
    String,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from whatisup.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from whatisup.models.monitor import Monitor


_JSON = JSON().with_variant(JSONB(), "postgresql")


class SLORuleType(enum.StrEnum):
    quorum_down = "quorum_down"
    quorum_slow = "quorum_slow"
    burn_rate = "burn_rate"


class MonitorHealthState(Base):
    """Rolling fleet-level health for a monitor — single row per monitor.

    Updated by ``services/health.ingest()`` after every CheckResult is persisted.
    Stores per-probe last state, p50/p95/p99 over 5 min, and serialized
    T-Digests for 1 h / 6 h / 24 h windows.
    """

    __tablename__ = "monitor_health_states"

    monitor_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("monitors.id", ondelete="CASCADE"),
        primary_key=True,
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # { probe_id: { last_status, last_at, consecutive_down, response_time_ms } }
    probes_state: Mapped[dict] = mapped_column(_JSON, default=dict, nullable=False)

    # 5-minute rolling percentiles (recomputed each ingest)
    p50_5m: Mapped[float | None] = mapped_column(Float, nullable=True)
    p95_5m: Mapped[float | None] = mapped_column(Float, nullable=True)
    p99_5m: Mapped[float | None] = mapped_column(Float, nullable=True)
    sample_count_5m: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Serialized T-Digest blobs for longer windows — populated incrementally
    tdigest_1h: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    tdigest_6h: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    tdigest_24h: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)

    # Quorum/scope summary used by SLO evaluators
    quorum_down_ratio: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    current_scope: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # { probe_id: { divergence_score, samples, last_eval_at } }
    probe_health: Mapped[dict] = mapped_column(_JSON, default=dict, nullable=False)

    monitor: Mapped[Monitor] = relationship("Monitor", back_populates="health_state")


class SLORule(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Server-side SLO rule evaluated continuously on each ingest.

    Replaces per-probe ``AlertRule`` perf checks once a monitor opts into the
    Global Health Engine (``Monitor.health_engine_enabled``).
    """

    __tablename__ = "slo_rules"

    # No `index=True`: ``ix_slo_rules_monitor_enabled`` below already leads on
    # ``monitor_id``, so a standalone index on it would never be chosen.
    monitor_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("monitors.id", ondelete="CASCADE"),
        nullable=False,
    )
    rule_type: Mapped[SLORuleType] = mapped_column(
        Enum(SLORuleType, name="slo_rule_type"), nullable=False
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # quorum_down: open if >= quorum_ratio probes are down over window_seconds
    quorum_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    window_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # quorum_slow: open if fleet p95 > p95_threshold_ms over window_seconds
    p95_threshold_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # burn_rate (phase 2): open if SLO burn-rate > burn_factor on window_seconds
    slo_target: Mapped[float | None] = mapped_column(Float, nullable=True)
    burn_factor: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Common
    min_probes: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    cooldown_seconds: Mapped[int] = mapped_column(Integer, default=60, nullable=False)

    monitor: Mapped[Monitor] = relationship("Monitor", back_populates="slo_rules")

    __table_args__ = (Index("ix_slo_rules_monitor_enabled", "monitor_id", "enabled"),)
