"""Hourly rollup of ``check_results`` (plan V2, A-2).

Every analytical query in ``services/stats.py`` currently scans the raw table:
90 days for one monitor is 115 k rows out of 4.9 M and the planner (measured,
plan_v2.md § "Résultats A-0") gives up on the btree and seq-scans 1.4 GB. The
same 90 days expressed as hourly buckets is ~2 200 rows.

Grain — deliberately **not** the ``(monitor_id, probe_id, bucket)`` announced in
the plan, but ``(monitor_id, bucket)``. Two reasons, both of which would make a
per-probe grain unusable for the very functions A-3 has to rebrand:

* **Uptime is a cross-probe consensus.** ``_aggregate_consensus`` groups checks
  per (network view, minute) and calls the minute up if *any* probe saw it up.
  Per-probe counters cannot answer that: they lose which probe's failure
  coincided with another probe's success. The consensus windows are therefore
  resolved at rollup time and stored as counters, which are additive across
  buckets — summing 24 hourly rows yields exactly the daily figure.
* **Percentiles do not pool.** p95 of two probe rows is not the p95 of their
  union, so a per-probe grain would force an approximation on the one endpoint
  (``compute_percentile_timeseries``) that is exact today.

What *is* an approximation, and stays one: percentiles over a window wider than
an hour, since they are re-aggregated from per-hour percentiles. Sample counts,
status counts, consensus uptime, average/min/max response time all stay exact
at any width.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from whatisup.models.base import Base


class CheckRollup1h(Base):
    """One row per monitor per UTC hour, built by ``services/rollup.py``.

    Rows are only written for hours that actually hold check results, and only
    once the hour is closed — the current partial hour is always served from
    the raw table so the live view stays exact.
    """

    __tablename__ = "check_rollups_1h"

    monitor_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("monitors.id", ondelete="CASCADE"),
        primary_key=True,
    )
    #: Start of the UTC hour this row summarises (``date_trunc('hour', …)``).
    bucket: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)

    #: Raw rows folded into this bucket — *not* the consensus total below.
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    up_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    down_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    timeout_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Consensus windows, per network view — the unit uptime percentages are
    # computed from (see whatisup.services.stats._aggregate_consensus). A window
    # is one (view, minute) pair; it counts as up if any probe of that view saw
    # the monitor up. Results with no probe attached count as external, exactly
    # as the raw-path aggregation does.
    internal_windows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    internal_up_windows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    external_windows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    external_up_windows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Response time. ``rt_sum``/``rt_count`` rather than a stored average, so a
    # multi-hour average stays exact instead of averaging averages.
    rt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rt_sum: Mapped[float | None] = mapped_column(Float, nullable=True)
    rt_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    rt_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    p50_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    p95_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    p99_ms: Mapped[float | None] = mapped_column(Float, nullable=True)

    #: When the bucket was last (re)built — a bucket is rebuilt for a few hours
    #: after it closes so late-arriving results are not lost.
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # The PK already indexes (monitor_id, bucket) for the per-monitor range
    # queries. This one serves the opposite access pattern: retention deleting
    # everything older than a cutoff, across all monitors (plan V2, A-4).
    __table_args__ = (Index("ix_check_rollups_1h_bucket", "bucket"),)
