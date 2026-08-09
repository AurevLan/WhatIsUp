"""Custom push metrics model.

Monthly range-partitioned on ``pushed_at`` since plan V2, C-2 (migration
``c2d3e4f5a6b7``), for the same reason as ``check_results``: this is the second
table whose size is driven by time rather than by configuration, and the only
one whose ceiling is set by the tenant's own application rather than by the
check schedule. It was, until then, the one time-series table with **no
retention at all** — nothing purged it, ever.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from whatisup.models.base import Base


class CustomMetric(Base):
    __tablename__ = "custom_metrics"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    monitor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("monitors.id", ondelete="CASCADE"), nullable=False
    )
    metric_name: Mapped[str] = mapped_column(String(100), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # Part of the primary key since C-2: a partitioned table's unique
    # constraints must contain the partition key. ``id`` alone is therefore no
    # longer globally unique — it is a client-side uuid4 and nothing in the
    # schema references it, so this is a formality (same trade-off as
    # CheckResult.checked_at, see migration e6f7a8b9c0d1).
    pushed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        primary_key=True,
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    # ``postgresql_partition_by`` only affects CREATE TABLE, so it is inert for
    # migrations and ignored by SQLite — the model stays identical on both
    # backends. The partitions are managed at runtime by whatisup.core.partitions.
    __table_args__ = (
        Index("ix_custom_metrics_monitor_time", "monitor_id", "pushed_at"),
        {"postgresql_partition_by": "RANGE (pushed_at)"},
    )
