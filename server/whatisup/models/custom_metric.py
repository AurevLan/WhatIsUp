"""Custom push metrics — points and their series registry.

Monthly range-partitioned on ``pushed_at`` since plan V2, C-2 (migration
``c2d3e4f5a6b7``), for the same reason as ``check_results``: this is the second
table whose size is driven by time rather than by configuration, and the only
one whose ceiling is set by the tenant's own application rather than by the
check schedule. It was, until then, the one time-series table with **no
retention at all** — nothing purged it, ever.

Since C-1 a point also carries ``labels``, so a metric name can be broken down
by dimension (``http_latency{route="/api", method="GET"}``). That turns a
*name* into a *family of series*, and a family of series is exactly what makes
this kind of table explode: one unbounded label — a user id, a request id — and
the row count stops being governed by how often you push and starts being
governed by how many distinct values your application happens to see.

Hence ``MetricSeries``: a small registry with one row per distinct
``(monitor, name, labels)``. It exists so the cardinality ceiling can be
enforced with a bounded ``COUNT(*)`` on a small table instead of a
``COUNT(DISTINCT …)`` across every partition of the points table — and it earns
its keep twice over, since the UI lists series from it and C-4's label selector
resolves against it.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from whatisup.models.base import Base

#: jsonb on PostgreSQL, plain JSON on SQLite (tests). Never bare ``JSON``:
#: containment queries and GIN indexes need the binary type.
_JSON = JSON().with_variant(JSONB(), "postgresql")


def series_hash(metric_name: str, labels: dict[str, str] | None) -> str:
    """Stable identity of a series within a monitor.

    Hashed rather than stored as a composite unique key on ``labels`` itself:
    two label dicts that differ only in key order are the same series, and a
    unique index over a JSON column would not agree. Sorting the keys before
    serialising is what makes the hash canonical, so the caller may pass labels
    in whatever order the client sent them.
    """
    canonical = json.dumps(
        {"n": metric_name, "l": dict(sorted((labels or {}).items()))},
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()[:32]


class CustomMetric(Base):
    __tablename__ = "custom_metrics"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    monitor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("monitors.id", ondelete="CASCADE"), nullable=False
    )
    metric_name: Mapped[str] = mapped_column(String(100), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # C-1 — dimensions. Empty dict, never NULL: "no labels" is a series like any
    # other, and letting it be NULL would make every containment query and every
    # hash have to special-case it.
    labels: Mapped[dict] = mapped_column(_JSON, nullable=False, default=dict, server_default="{}")
    # Denormalised copy of ``series_hash(metric_name, labels)``. Carried on the
    # point so a series lookup is an equality on one indexed column rather than
    # a JSON containment across partitions.
    #
    # Derived from the row's own values rather than left to the caller: every
    # writer then gets it right by construction, and it stays consistent for
    # code that builds a ``CustomMetric`` directly (tests, fixtures, imports).
    # A Python-side default also keeps the insert out of SQLAlchemy's
    # insertmanyvalues RETURNING path, which cannot match sentinel values on
    # this table — composite PK plus a timezone-aware datetime SQLite hands
    # back naive.
    series_hash: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default="",
        default=lambda ctx: series_hash(
            ctx.get_current_parameters()["metric_name"],
            ctx.get_current_parameters().get("labels"),
        ),
    )
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
        # The read path of every consumer (C-4's evaluator, the charts): one
        # series, most recent first, bounded in time.
        Index("ix_custom_metrics_series_time", "monitor_id", "series_hash", "pushed_at"),
        {"postgresql_partition_by": "RANGE (pushed_at)"},
    )


class MetricSeries(Base):
    """One row per distinct ``(monitor, metric_name, labels)`` ever pushed.

    Not partitioned and not time-series: it is bounded by configuration (the
    per-monitor cardinality cap), not by time. Purged by the retention job when
    a series stops reporting for longer than the metric retention window, so a
    renamed or decommissioned series eventually frees its slot under the cap.
    """

    __tablename__ = "metric_series"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    monitor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("monitors.id", ondelete="CASCADE"), nullable=False, index=True
    )
    metric_name: Mapped[str] = mapped_column(String(100), nullable=False)
    labels: Mapped[dict] = mapped_column(_JSON, nullable=False, default=dict, server_default="{}")
    series_hash: Mapped[str] = mapped_column(String(32), nullable=False)
    unit: Mapped[str | None] = mapped_column(String(50), nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    #: Advanced on every ingest. Drives both the retention purge and the "is
    #: this series still alive?" answer the UI shows.
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC), index=True
    )

    __table_args__ = (
        # Named UNIQUE constraint, not ``unique=True`` on the column: the latter
        # asks for an ``ix_…`` unique *index*, which is not the same object and
        # makes autogenerate propose to rebuild it forever (CLAUDE.md).
        UniqueConstraint("monitor_id", "series_hash", name="uq_metric_series_monitor_hash"),
        Index("ix_metric_series_monitor_name", "monitor_id", "metric_name"),
        # Containment lookups (``labels @> '{"route":"/api"}'``) for C-4's
        # selector. PostgreSQL-only, hence ddl_if; the operator class goes in
        # ``postgresql_ops`` rather than inline, or alembic gives up comparing
        # the expression and can no longer vouch for the index (CLAUDE.md).
        Index(
            "ix_metric_series_labels_gin",
            text("labels"),
            postgresql_using="gin",
            postgresql_ops={"labels": "jsonb_path_ops"},
        ).ddl_if(dialect="postgresql"),
    )
