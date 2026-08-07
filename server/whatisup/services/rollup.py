"""Incremental builder for the hourly rollup table (plan V2, A-2).

Runs as a leader-gated background loop (``main.py``) and folds closed hours of
``check_results`` into :class:`~whatisup.models.rollup.CheckRollup1h`.

Design notes
────────────

**Aggregation happens in Python, not in SQL.** The tempting version is a single
``INSERT … SELECT … GROUP BY date_trunc('hour', …)`` with ``percentile_cont``,
but the consensus rule it has to reproduce (see the model docstring) is not a
plain GROUP BY, and the test suite runs on SQLite, which has neither
``date_trunc`` nor ``percentile_cont``. Two implementations of the same
semantics would drift, and the one that matters — the PostgreSQL one — would be
the untested one. Folding rows in Python keeps a single source of truth and
makes the whole thing verifiable on SQLite. The cost is bounded: steady state is
one hour of rows per run (~2 500 at the measured 60 500/day), and the initial
backfill is chunked by day.

**Nothing purges the table yet.** At the measured fleet size a year of buckets
is ~140 k rows (a few tens of MB), and giving rollups their own retention is
A-4's job — outliving the raw window is the whole point of having them.

**No watermark table.** The resume point is derived: ``max(bucket)`` already in
the rollups, minus a few hours so late-arriving results are folded in, and if
there is nothing yet, the first ``checked_at`` in the raw table. A gap in the
data (a server down for weeks) cannot stall the loop either — the start is
snapped forward to the first hour that actually holds a result, so empty spans
are skipped in one query instead of being re-scanned window by window forever.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.core.database import dialect_name
from whatisup.models.probe import NetworkType, Probe
from whatisup.models.result import CheckResult, CheckStatus
from whatisup.models.rollup import CheckRollup1h

logger = structlog.get_logger(__name__)

#: Hours folded in one run. 168 (a week) keeps a 90-day backfill to ~13 runs
#: while a single run never reads more than a week of raw rows.
DEFAULT_MAX_BUCKETS = 168

#: How far back a run rewinds before its watermark. Results are pushed by
#: probes and can land after their hour closed (retry, clock skew, a probe that
#: was offline); rebuilding the last few hours picks them up. Upserts make this
#: free of side effects.
DEFAULT_RECOMPUTE_HOURS = 3

#: Raw rows are read in slices of this many hours to bound memory during the
#: initial backfill (a day is ~60 500 rows).
_READ_CHUNK_HOURS = 24


def floor_hour(moment: datetime) -> datetime:
    """Start of ``moment``'s UTC hour."""
    return moment.astimezone(UTC).replace(minute=0, second=0, microsecond=0)


def percentile_cont(sorted_values: list[float], q: float) -> float | None:
    """Linear-interpolation percentile, matching PostgreSQL ``percentile_cont``.

    Deliberately the same definition as the SQL the rollups replace
    (``compute_percentile_timeseries``), so switching a chart over to the
    rollup table does not shift its numbers.
    """
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = (len(sorted_values) - 1) * q
    low = int(pos)
    high = min(low + 1, len(sorted_values) - 1)
    if low == high:
        return sorted_values[low]
    return sorted_values[low] + (sorted_values[high] - sorted_values[low]) * (pos - low)


@dataclass
class _Bucket:
    """Mutable accumulator for one (monitor, hour) pair."""

    sample_count: int = 0
    status_counts: dict[CheckStatus, int] = field(default_factory=lambda: defaultdict(int))
    rt_values: list[float] = field(default_factory=list)
    #: (network view, minute) → any probe of that view saw the monitor up
    windows: dict[tuple[NetworkType, datetime], bool] = field(default_factory=dict)

    def add(
        self,
        checked_at: datetime,
        status: CheckStatus,
        response_time_ms: float | None,
        network_type: NetworkType | None,
    ) -> None:
        self.sample_count += 1
        self.status_counts[status] += 1
        if response_time_ms is not None:
            self.rt_values.append(response_time_ms)
        # A result with no probe counts as external — same fallback as the raw
        # path in stats._aggregate_consensus, so both agree.
        view = network_type or NetworkType.external
        key = (view, checked_at.replace(second=0, microsecond=0))
        self.windows[key] = self.windows.get(key, False) or status == CheckStatus.up

    def as_row(self, monitor_id: uuid.UUID, bucket: datetime, computed_at: datetime) -> dict:
        rt = sorted(self.rt_values)
        totals: dict[NetworkType, list[int]] = defaultdict(lambda: [0, 0])
        for (view, _minute), is_up in self.windows.items():
            totals[view][0] += 1
            if is_up:
                totals[view][1] += 1
        internal, external = totals[NetworkType.internal], totals[NetworkType.external]
        return {
            "monitor_id": monitor_id,
            "bucket": bucket,
            "sample_count": self.sample_count,
            "up_count": self.status_counts[CheckStatus.up],
            "down_count": self.status_counts[CheckStatus.down],
            "timeout_count": self.status_counts[CheckStatus.timeout],
            "error_count": self.status_counts[CheckStatus.error],
            "internal_windows": internal[0],
            "internal_up_windows": internal[1],
            "external_windows": external[0],
            "external_up_windows": external[1],
            "rt_count": len(rt),
            "rt_sum": sum(rt) if rt else None,
            "rt_min": rt[0] if rt else None,
            "rt_max": rt[-1] if rt else None,
            "p50_ms": percentile_cont(rt, 0.50),
            "p95_ms": percentile_cont(rt, 0.95),
            "p99_ms": percentile_cont(rt, 0.99),
            "computed_at": computed_at,
        }


async def _resume_point(db: AsyncSession, *, recompute_hours: int) -> datetime | None:
    """First hour to (re)build, or None when there is nothing to fold.

    Snaps forward to the first hour that actually holds a check result so a gap
    in the data — retention having dropped a month, a server down for weeks —
    is crossed in one query instead of stalling the loop on empty windows.
    """
    watermark = (await db.execute(select(func.max(CheckRollup1h.bucket)))).scalar_one_or_none()
    start = None
    if watermark is not None:
        if watermark.tzinfo is None:  # SQLite hands back naive datetimes
            watermark = watermark.replace(tzinfo=UTC)
        # The hour *after* the watermark is the first one not yet built; the
        # rewind then reaches back over the last ``recompute_hours`` of it. With
        # a zero rewind the builder therefore never redoes a bucket, and once it
        # has caught up it has nothing left to do.
        start = floor_hour(watermark) + timedelta(hours=1 - recompute_hours)

    stmt = select(func.min(CheckResult.checked_at))
    if start is not None:
        stmt = stmt.where(CheckResult.checked_at >= start)
    first = (await db.execute(stmt)).scalar_one_or_none()
    if first is None:
        return None
    if first.tzinfo is None:
        first = first.replace(tzinfo=UTC)
    return floor_hour(first)


async def _fold_range(db: AsyncSession, start: datetime, end: datetime) -> dict:
    """Aggregate raw rows in ``[start, end)`` into ``{(monitor_id, bucket): _Bucket}``."""
    buckets: dict[tuple[uuid.UUID, datetime], _Bucket] = {}
    stmt = (
        select(
            CheckResult.monitor_id,
            CheckResult.checked_at,
            CheckResult.status,
            CheckResult.response_time_ms,
            Probe.network_type,
        )
        .outerjoin(Probe, CheckResult.probe_id == Probe.id)
        .where(CheckResult.checked_at >= start, CheckResult.checked_at < end)
    )
    for row in (await db.execute(stmt)).all():
        checked_at = row.checked_at
        if checked_at.tzinfo is None:
            checked_at = checked_at.replace(tzinfo=UTC)
        key = (row.monitor_id, floor_hour(checked_at))
        bucket = buckets.get(key)
        if bucket is None:
            bucket = buckets[key] = _Bucket()
        bucket.add(checked_at, row.status, row.response_time_ms, row.network_type)
    return buckets


async def _upsert(db: AsyncSession, rows: list[dict]) -> None:
    """Insert-or-replace rollup rows (both backends support ON CONFLICT)."""
    if not rows:
        return
    insert = pg_insert if dialect_name(db) == "postgresql" else sqlite_insert
    stmt = insert(CheckRollup1h).values(rows)
    updatable = [
        c.name for c in CheckRollup1h.__table__.columns if c.name not in ("monitor_id", "bucket")
    ]
    await db.execute(
        stmt.on_conflict_do_update(
            index_elements=["monitor_id", "bucket"],
            set_={name: getattr(stmt.excluded, name) for name in updatable},
        )
    )


async def rebuild_range(db: AsyncSession, start: datetime, end: datetime) -> int:
    """(Re)build every bucket in ``[start, end)`` and return the rows written.

    The unconditional half of the builder: no watermark, no horizon, no cap —
    exactly the hours asked for. :func:`build_rollups` uses it for its own
    window, and it is the primitive to reach for when a range has to be redone
    (results imported after the fact, a bug fixed in the aggregation).

    Rows are committed per read chunk so a long backfill never holds one
    transaction open across the whole span.
    """
    written = 0
    computed_at = datetime.now(UTC)
    chunk_start = start
    while chunk_start < end:
        chunk_end = min(end, chunk_start + timedelta(hours=_READ_CHUNK_HOURS))
        buckets = await _fold_range(db, chunk_start, chunk_end)
        rows = [
            acc.as_row(monitor_id, bucket, computed_at)
            for (monitor_id, bucket), acc in sorted(buckets.items(), key=lambda kv: kv[0][1])
        ]
        await _upsert(db, rows)
        await db.commit()
        written += len(rows)
        chunk_start = chunk_end
    return written


async def build_rollups(
    db: AsyncSession,
    *,
    now: datetime | None = None,
    max_buckets: int = DEFAULT_MAX_BUCKETS,
    recompute_hours: int = DEFAULT_RECOMPUTE_HOURS,
) -> int:
    """Fold closed hours of ``check_results`` into ``check_rollups_1h``.

    Idempotent: a bucket already built is simply rewritten with the same values.
    Returns the number of rollup rows written.

    Only hours strictly before the current one are folded — the in-progress
    hour keeps changing, and consumers read it from the raw table anyway
    (plan V2, A-3 keeps the raw path for the recent window).
    """
    now = now or datetime.now(UTC)
    horizon = floor_hour(now)

    start = await _resume_point(db, recompute_hours=recompute_hours)
    if start is None or start >= horizon:
        return 0
    end = min(horizon, start + timedelta(hours=max_buckets))

    written = await rebuild_range(db, start, end)
    if written:
        logger.info(
            "rollups_built",
            rows=written,
            start=start.isoformat(),
            end=end.isoformat(),
            behind_hours=int((horizon - end).total_seconds() // 3600),
        )
    return written
