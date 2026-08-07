"""Uptime and response time statistics service.

Multi-probe consensus
─────────────────────
A monitor with several probes is considered "up" for a given time window as
long as **at least one probe in the same network view** (internal / external)
saw the service up. This avoids the false dip in uptime that happens when one
probe is broken or temporarily unreachable while the others are reporting up.

The window granularity is 1 minute, which lines up with the smallest typical
monitor interval. Two probes that check at 12:00:05 and 12:00:42 fall in the
same minute bucket and are treated as one consensus observation.

The global ``uptime_percent`` is the **worst** of the per-view percentages so
a regional outage (e.g. only the external view is down) still shows up. The
per-view fields ``internal_uptime_percent`` / ``external_uptime_percent`` let
the UI break the number down explicitly.

Rollups vs raw (plan V2, A-3)
─────────────────────────────
The analytical functions (daily history, percentile series, custom range) read
``check_rollups_1h`` for the hours it covers and the raw table for the rest —
the hour in progress, the sliver before the first whole hour of the window, and
anything the builder has not folded yet. The split is derived from
``max(bucket) + 1 h`` and needs no configuration: with an empty rollup table
(fresh install, builder disabled) every window falls through to the raw path,
which is the behaviour that predates A-3.

Both sources feed the same accumulator, and the split is always on an hour
boundary — a consensus window (view, minute) therefore belongs to exactly one
of them, so their counters simply add up. Everything stays exact except p95
over a window wider than an hour, which is re-aggregated from hourly p95s and
flagged as such (``p95_is_estimate``).
"""

from __future__ import annotations

import json
import uuid
from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, text, true
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from whatisup.core.database import dialect_name
from whatisup.models.monitor import Monitor
from whatisup.models.probe import NetworkType, Probe
from whatisup.models.result import CheckResult, CheckStatus
from whatisup.models.rollup import CheckRollup1h
from whatisup.schemas.result import UptimeStats
from whatisup.services.rollup import floor_hour, percentile_cont


def latest_results_subq(*where_clauses: Any, group_col: Any) -> Any:
    """Return a subquery: SELECT group_col, MAX(checked_at) AS max_at GROUP BY group_col.

    Used to batch-fetch the most recent CheckResult per monitor or probe,
    avoiding N+1 queries in list endpoints and incident processing.

    Usage example (latest per monitor):
        subq = latest_results_subq(
            CheckResult.monitor_id.in_(ids), group_col=CheckResult.monitor_id
        )
        rows = await db.execute(
            select(CheckResult).join(
                subq,
                (CheckResult.monitor_id == subq.c.monitor_id)
                & (CheckResult.checked_at == subq.c.max_at),
            )
        )
    """
    return (
        select(group_col, func.max(CheckResult.checked_at).label("max_at"))
        .where(*where_clauses)
        .group_by(group_col)
        .subquery()
    )


async def fetch_latest_results(
    db: AsyncSession,
    monitor_ids: Sequence[uuid.UUID],
) -> dict[uuid.UUID, CheckResult]:
    """Latest CheckResult per monitor, keyed by monitor_id.

    On PostgreSQL a ``max(checked_at)`` self-join aggregates every historical
    row of the listed monitors (seconds on millions of rows — see #218); a
    LATERAL ``ORDER BY checked_at DESC LIMIT 1`` hits
    ix_check_results_monitor_checked once per monitor for a single row.
    SQLite (tests) keeps the self-join: LATERAL support is not uniformly
    available in test containers, and test tables are tiny.

    Monitors with no results are absent from the returned dict.
    """
    if not monitor_ids:
        return {}
    if dialect_name(db) == "sqlite":
        subq = latest_results_subq(
            CheckResult.monitor_id.in_(monitor_ids), group_col=CheckResult.monitor_id
        )
        rows = (
            (
                await db.execute(
                    select(CheckResult).join(
                        subq,
                        (CheckResult.monitor_id == subq.c.monitor_id)
                        & (CheckResult.checked_at == subq.c.max_at),
                    )
                )
            )
            .scalars()
            .all()
        )
    else:
        lateral = (
            select(CheckResult)
            .where(CheckResult.monitor_id == Monitor.id)
            .order_by(CheckResult.checked_at.desc())
            .limit(1)
            .lateral("latest_cr")
        )
        latest_cr = aliased(CheckResult, lateral)
        rows = (
            (
                await db.execute(
                    select(latest_cr)
                    .select_from(Monitor.__table__.join(lateral, true()))
                    .where(Monitor.id.in_(monitor_ids))
                )
            )
            .scalars()
            .all()
        )
    return {r.monitor_id: r for r in rows}


async def invalidate_uptime_cache(monitor_id: uuid.UUID) -> None:
    """Delete all cached uptime entries for a monitor (called on new check result)."""
    from whatisup.core.redis import get_redis

    redis = get_redis()
    pattern = f"whatisup:uptime:{monitor_id}:*"
    async for key in redis.scan_iter(match=pattern):
        await redis.delete(key)


def _aggregate_consensus(
    rows: Iterable[tuple[datetime, CheckStatus, float | None, NetworkType | None]],
) -> tuple[float | None, float | None, int, int, float | None, float | None]:
    """Group raw check rows into consensus windows and return view stats.

    Returns:
        ``(internal_pct, external_pct, total_windows, up_windows, avg_rt, p95_rt)``
        where percentages are 0-100 floats and ``None`` for views that have no
        active probes in the period.
    """
    # bucket key: (network_type, minute) → list of "is_up" booleans
    buckets: dict[tuple[NetworkType, datetime], list[bool]] = defaultdict(list)
    rt_values: list[float] = []

    for checked_at, status, rt, ntype in rows:
        if ntype is None:
            # Result without an associated probe — treat it as external by default
            ntype = NetworkType.external
        minute = checked_at.replace(second=0, microsecond=0)
        buckets[(ntype, minute)].append(status == CheckStatus.up)
        if rt is not None:
            rt_values.append(rt)

    view_totals: dict[NetworkType, list[int]] = defaultdict(lambda: [0, 0])
    for (ntype, _minute), ups in buckets.items():
        view_totals[ntype][0] += 1
        if any(ups):
            view_totals[ntype][1] += 1

    def _pct(view: NetworkType) -> float | None:
        total, up = view_totals.get(view, [0, 0])
        if total == 0:
            return None
        return round(up / total * 100, 3)

    internal_pct = _pct(NetworkType.internal)
    external_pct = _pct(NetworkType.external)

    total_windows = sum(t for t, _ in view_totals.values())
    up_windows = sum(u for _, u in view_totals.values())

    avg_rt = sum(rt_values) / len(rt_values) if rt_values else None
    p95_rt: float | None
    if rt_values:
        sorted_rt = sorted(rt_values)
        idx = max(0, min(len(sorted_rt) - 1, int(round(len(sorted_rt) * 0.95)) - 1))
        p95_rt = sorted_rt[idx]
    else:
        p95_rt = None

    return internal_pct, external_pct, total_windows, up_windows, avg_rt, p95_rt


def _legacy_p95(values: Sequence[float]) -> float | None:
    """Nearest-rank p95, the convention ``_aggregate_consensus`` has always used.

    Kept for the raw-only path so a deployment without rollups keeps returning
    the exact numbers it returned before A-3.
    """
    if not values:
        return None
    ordered = sorted(values)
    idx = max(0, min(len(ordered) - 1, int(round(len(ordered) * 0.95)) - 1))
    return ordered[idx]


class _Aggregate:
    """Consensus + response-time counters, fed from rollups, raw rows, or both.

    The two sources always cover disjoint hour ranges, so their contributions
    add: a consensus window (view, minute) lives in exactly one hour, hence in
    exactly one source. Raw rows still have to be folded into minute windows
    here — that is what makes a mixed window (rollups for the closed hours, raw
    for the hour in progress) come out identical to the all-raw computation.
    """

    def __init__(self) -> None:
        #: (view, minute) → any probe of that view saw the monitor up
        self._windows: dict[tuple[NetworkType, datetime], bool] = {}
        #: view → [windows, up windows] contributed by rollup buckets
        self._views: dict[NetworkType, list[int]] = defaultdict(lambda: [0, 0])
        self.rt_count = 0
        self.rt_sum = 0.0
        self.rt_min: float | None = None
        self.rt_max: float | None = None
        self._raw_rt: list[float] = []
        #: (hourly p95, samples in that hour) — the only lossy part of a rollup
        self._p95_parts: list[tuple[float, int]] = []

    def _track_extremes(self, low: float | None, high: float | None) -> None:
        if low is not None:
            self.rt_min = low if self.rt_min is None else min(self.rt_min, low)
        if high is not None:
            self.rt_max = high if self.rt_max is None else max(self.rt_max, high)

    def add_rollup(self, row: Any) -> None:
        self._views[NetworkType.internal][0] += row.internal_windows
        self._views[NetworkType.internal][1] += row.internal_up_windows
        self._views[NetworkType.external][0] += row.external_windows
        self._views[NetworkType.external][1] += row.external_up_windows
        if row.rt_count:
            self.rt_count += row.rt_count
            self.rt_sum += row.rt_sum or 0.0
            self._track_extremes(row.rt_min, row.rt_max)
            if row.p95_ms is not None:
                self._p95_parts.append((row.p95_ms, row.rt_count))

    def add_raw(
        self,
        checked_at: datetime,
        status: CheckStatus,
        response_time_ms: float | None,
        network_type: NetworkType | None,
    ) -> None:
        # A result with no probe counts as external — same fallback as
        # _aggregate_consensus and as the rollup builder.
        view = network_type or NetworkType.external
        key = (view, checked_at.replace(second=0, microsecond=0))
        self._windows[key] = self._windows.get(key, False) or status == CheckStatus.up
        if response_time_ms is not None:
            self.rt_count += 1
            self.rt_sum += response_time_ms
            self._raw_rt.append(response_time_ms)
            self._track_extremes(response_time_ms, response_time_ms)

    def views(self) -> tuple[float | None, float | None, int, int]:
        """``(internal_pct, external_pct, total_windows, up_windows)``."""
        totals = {view: list(counts) for view, counts in self._views.items()}
        for (view, _minute), is_up in self._windows.items():
            slot = totals.setdefault(view, [0, 0])
            slot[0] += 1
            if is_up:
                slot[1] += 1

        def _pct(view: NetworkType) -> float | None:
            total, up = totals.get(view, [0, 0])
            return round(up / total * 100, 3) if total else None

        return (
            _pct(NetworkType.internal),
            _pct(NetworkType.external),
            sum(total for total, _ in totals.values()),
            sum(up for _, up in totals.values()),
        )

    @property
    def avg_rt(self) -> float | None:
        return self.rt_sum / self.rt_count if self.rt_count else None

    def p95(self) -> tuple[float | None, bool]:
        """``(value, is_estimate)``.

        Exact — and bit-for-bit what the pre-A-3 code returned — when the window
        is served entirely from raw rows. As soon as a rollup bucket takes part,
        the answer is a sample-weighted mean of the hourly p95s: percentiles do
        not re-aggregate, and storing a digest per bucket would be a different
        (much larger) design. Flagged so callers can say so.
        """
        if not self._p95_parts:
            return _legacy_p95(self._raw_rt), False
        parts = list(self._p95_parts)
        if self._raw_rt:
            raw_p95 = percentile_cont(sorted(self._raw_rt), 0.95)
            if raw_p95 is not None:
                parts.append((raw_p95, len(self._raw_rt)))
        weight = sum(count for _, count in parts)
        if not weight:
            return None, False
        return sum(value * count for value, count in parts) / weight, True

    def daily_entry(self, day: date) -> dict:
        internal_pct, external_pct, total, up = self.views()
        avg_rt = self.avg_rt
        return {
            "date": day.isoformat(),
            "total": total,
            "up_count": up,
            "uptime_percent": round(_global_uptime(internal_pct, external_pct), 2),
            "internal_uptime_percent": internal_pct,
            "external_uptime_percent": external_pct,
            "avg_response_time_ms": round(avg_rt, 1) if avg_rt is not None else None,
        }


def _ceil_hour(moment: datetime) -> datetime:
    floored = floor_hour(moment)
    return floored if floored == moment else floored + timedelta(hours=1)


async def _rollup_boundary(db: AsyncSession) -> datetime | None:
    """First instant *not* covered by the rollups, or None if there are none.

    The builder walks forward in time from the oldest raw row and never folds
    the hour in progress, so every hour below ``max(bucket) + 1 h`` has been
    processed — written if it held results, legitimately absent otherwise.
    Above it, only the raw table knows.
    """
    watermark = (await db.execute(select(func.max(CheckRollup1h.bucket)))).scalar_one_or_none()
    if watermark is None:
        return None
    if watermark.tzinfo is None:  # SQLite hands back naive datetimes
        watermark = watermark.replace(tzinfo=UTC)
    return floor_hour(watermark) + timedelta(hours=1)


async def _rollup_window(
    db: AsyncSession, start: datetime, end: datetime
) -> tuple[datetime, datetime]:
    """Sub-range of ``[start, end]`` the rollups may serve, as whole hours.

    Empty (``start, start``) when there is nothing usable — no rollups at all,
    or a window too narrow to contain a whole covered hour.
    """
    boundary = await _rollup_boundary(db)
    if boundary is None:
        return start, start
    rollup_start = _ceil_hour(start)
    rollup_end = min(boundary, floor_hour(end))
    if rollup_end <= rollup_start:
        return start, start
    return rollup_start, rollup_end


def _raw_gaps(
    start: datetime, end: datetime, rollup_start: datetime, rollup_end: datetime
) -> list[tuple[datetime, datetime]]:
    """The parts of ``[start, end]`` the rollups do not cover."""
    if rollup_end <= rollup_start:
        return [(start, end)]
    return [span for span in ((start, rollup_start), (rollup_end, end)) if span[0] < span[1]]


async def _fetch_rollup_rows(
    db: AsyncSession,
    monitor_ids: Sequence[uuid.UUID],
    start: datetime,
    end: datetime,
) -> Sequence[Any]:
    """Rollup buckets in ``[start, end)`` for the given monitors."""
    if not monitor_ids or start >= end:
        return []
    stmt = select(
        CheckRollup1h.monitor_id,
        CheckRollup1h.bucket,
        CheckRollup1h.internal_windows,
        CheckRollup1h.internal_up_windows,
        CheckRollup1h.external_windows,
        CheckRollup1h.external_up_windows,
        CheckRollup1h.rt_count,
        CheckRollup1h.rt_sum,
        CheckRollup1h.rt_min,
        CheckRollup1h.rt_max,
        CheckRollup1h.p50_ms,
        CheckRollup1h.p95_ms,
        CheckRollup1h.p99_ms,
    ).where(
        CheckRollup1h.monitor_id.in_(monitor_ids),
        CheckRollup1h.bucket >= start,
        CheckRollup1h.bucket < end,
    )
    return (await db.execute(stmt)).all()


def _global_uptime(internal_pct: float | None, external_pct: float | None) -> float:
    """Worst-of-views consensus uptime, defaults to 100% when no data."""
    if internal_pct is None and external_pct is None:
        return 100.0
    if internal_pct is None:
        return external_pct  # type: ignore[return-value]
    if external_pct is None:
        return internal_pct
    return min(internal_pct, external_pct)


async def _fetch_check_rows(
    db: AsyncSession,
    monitor_ids: Sequence[uuid.UUID],
    cutoff: datetime,
    end: datetime | None = None,
    *,
    inclusive_end: bool = False,
) -> list[tuple[uuid.UUID, datetime, CheckStatus, float | None, NetworkType | None]]:
    """Fetch raw check rows joined with probe network type — used by both
    single and bulk uptime computations to keep the algorithm in one place.

    ``end`` bounds the window on the right (exclusive unless ``inclusive_end``),
    which is what lets the analytical functions read only the slice the rollups
    do not cover.
    """
    if not monitor_ids:
        return []
    stmt = (
        select(
            CheckResult.monitor_id,
            CheckResult.checked_at,
            CheckResult.status,
            CheckResult.response_time_ms,
            Probe.network_type,
        )
        .outerjoin(Probe, CheckResult.probe_id == Probe.id)
        .where(
            CheckResult.monitor_id.in_(monitor_ids),
            CheckResult.checked_at >= cutoff,
        )
    )
    if end is not None:
        stmt = stmt.where(
            CheckResult.checked_at <= end if inclusive_end else CheckResult.checked_at < end
        )
    rows = (await db.execute(stmt)).all()
    return [
        (r.monitor_id, r.checked_at, r.status, r.response_time_ms, r.network_type) for r in rows
    ]


async def compute_uptime(
    db: AsyncSession,
    monitor_id: uuid.UUID,
    period_hours: int = 24,
) -> UptimeStats:
    from whatisup.core.redis import get_redis

    redis = get_redis()
    cache_key = f"whatisup:uptime:{monitor_id}:{period_hours}"
    cached = await redis.get(cache_key)
    if cached:
        data = json.loads(cached)
        return UptimeStats(**data)

    cutoff = datetime.now(UTC) - timedelta(hours=period_hours)
    rows = await _fetch_check_rows(db, [monitor_id], cutoff)
    monitor_rows = [(checked_at, status, rt, ntype) for _, checked_at, status, rt, ntype in rows]

    internal_pct, external_pct, total, up_count, avg_rt, p95_rt = _aggregate_consensus(monitor_rows)
    uptime_pct = _global_uptime(internal_pct, external_pct)

    stats = UptimeStats(
        monitor_id=monitor_id,
        period_hours=period_hours,
        total_checks=total,
        up_checks=up_count,
        uptime_percent=round(uptime_pct, 3),
        internal_uptime_percent=internal_pct,
        external_uptime_percent=external_pct,
        avg_response_time_ms=round(avg_rt, 1) if avg_rt is not None else None,
        p95_response_time_ms=round(p95_rt, 1) if p95_rt is not None else None,
    )

    await redis.setex(cache_key, 60, json.dumps(stats.model_dump(mode="json")))
    return stats


async def compute_uptime_in_range(
    db: AsyncSession,
    monitor_id: uuid.UUID,
    from_: datetime,
    to: datetime,
) -> dict[str, Any]:
    """Consensus uptime + response-time stats over an arbitrary time range.

    Used by SLA reports and SLO endpoints which need a custom window instead
    of a fixed period_hours. A 30-day SLO window is exactly the scan the
    rollups exist for, so whole covered hours are read from them (plan V2, A-3);
    only ``p95_response_time_ms`` is then an estimate, which the extra
    ``p95_is_estimate`` key states outright rather than leaving to a docstring.
    """
    rollup_start, rollup_end = await _rollup_window(db, from_, to)
    agg = _Aggregate()
    for row in await _fetch_rollup_rows(db, [monitor_id], rollup_start, rollup_end):
        agg.add_rollup(row)
    for gap_start, gap_end in _raw_gaps(from_, to, rollup_start, rollup_end):
        rows = await _fetch_check_rows(
            db, [monitor_id], gap_start, gap_end, inclusive_end=gap_end == to
        )
        for _mid, checked_at, status, rt, ntype in rows:
            agg.add_raw(checked_at, status, rt, ntype)

    internal_pct, external_pct, total, up = agg.views()
    avg_rt = agg.avg_rt
    p95_rt, p95_estimated = agg.p95()

    return {
        "total_checks": total,
        "up_checks": up,
        "uptime_percent": round(_global_uptime(internal_pct, external_pct), 4),
        "internal_uptime_percent": internal_pct,
        "external_uptime_percent": external_pct,
        "avg_response_time_ms": round(avg_rt, 1) if avg_rt is not None else None,
        "p95_response_time_ms": round(p95_rt, 1) if p95_rt is not None else None,
        "p95_is_estimate": p95_estimated,
        "min_response_time_ms": round(agg.rt_min, 1) if agg.rt_min is not None else None,
        "max_response_time_ms": round(agg.rt_max, 1) if agg.rt_max is not None else None,
    }


async def compute_uptime_bulk(
    db: AsyncSession,
    monitor_ids: Sequence[uuid.UUID],
    period_hours: int = 24,
) -> dict[str, dict[str, Any]]:
    """Bulk consensus uptime for many monitors in a single SQL round-trip.

    Returns a dict ``{str(monitor_id): {"uptime_percent": .., "internal_uptime_percent": .., ...}}``
    used by the monitors list endpoint to avoid N queries.
    """
    if not monitor_ids:
        return {}
    cutoff = datetime.now(UTC) - timedelta(hours=period_hours)
    rows = await _fetch_check_rows(db, monitor_ids, cutoff)

    by_monitor: dict[
        uuid.UUID,
        list[tuple[datetime, CheckStatus, float | None, NetworkType | None]],
    ] = defaultdict(list)
    for mid, checked_at, status, rt, ntype in rows:
        by_monitor[mid].append((checked_at, status, rt, ntype))

    out: dict[str, dict[str, Any]] = {}
    for mid, monitor_rows in by_monitor.items():
        internal_pct, external_pct, _total, _up, avg_rt, _p95 = _aggregate_consensus(monitor_rows)
        out[str(mid)] = {
            "uptime_percent": round(_global_uptime(internal_pct, external_pct), 2),
            "internal_uptime_percent": internal_pct,
            "external_uptime_percent": external_pct,
            "avg_response_time_ms": round(avg_rt, 1) if avg_rt is not None else None,
        }
    return out


async def compute_daily_history(
    db: AsyncSession,
    monitor_id: uuid.UUID,
    days: int = 90,
) -> list[dict]:
    """Daily consensus uptime for history bars.

    Uses the same multi-probe-consensus rule as ``compute_uptime`` so the daily
    bars and the headline number stay coherent.
    """
    return (await compute_daily_history_bulk(db, [monitor_id], days=days)).get(str(monitor_id), [])


async def compute_daily_history_bulk(
    db: AsyncSession,
    monitor_ids: Sequence[uuid.UUID],
    days: int = 90,
) -> dict[str, list[dict]]:
    """Bulk daily consensus history for many monitors.

    Returns ``{str(monitor_id): [day entries]}``. Used by the public status page,
    which asked for 90 days × every monitor and used to pay a 9.5 s scan of the
    raw table for it (measured, plan_v2.md § "Résultats A-0"); whole covered
    hours now come from the rollups, the tail from the raw table.

    Exact either way: a day is the sum of its hours, and consensus windows are
    counted per (view, minute), so no window can be split across the two
    sources.
    """
    if not monitor_ids:
        return {}
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=days)

    rollup_start, rollup_end = await _rollup_window(db, cutoff, now)
    aggs: dict[tuple[uuid.UUID, date], _Aggregate] = defaultdict(_Aggregate)
    for row in await _fetch_rollup_rows(db, monitor_ids, rollup_start, rollup_end):
        aggs[(row.monitor_id, row.bucket.date())].add_rollup(row)
    for gap_start, gap_end in _raw_gaps(cutoff, now, rollup_start, rollup_end):
        rows = await _fetch_check_rows(db, monitor_ids, gap_start, gap_end)
        for mid, checked_at, status, rt, ntype in rows:
            aggs[(mid, checked_at.date())].add_raw(checked_at, status, rt, ntype)

    out: dict[str, list[dict]] = defaultdict(list)
    for mid, day in sorted(aggs):
        out[str(mid)].append(aggs[(mid, day)].daily_entry(day))
    return dict(out)


async def _raw_percentile_buckets(
    db: AsyncSession,
    monitor_id: uuid.UUID,
    start: datetime,
    end: datetime,
) -> dict[datetime, dict]:
    """Hourly p50/p95/p99 straight from the raw table, keyed by bucket start.

    PostgreSQL aggregates server-side with ``percentile_cont``; SQLite has no
    such function (nor ``date_trunc``), so the tests' backend folds the rows in
    Python with the identical linear-interpolation definition — the one the
    rollup builder uses, and whose parity with PostgreSQL is a test.
    """
    if start >= end:
        return {}
    if dialect_name(db) == "postgresql":
        bucket = func.date_trunc(text("'hour'"), CheckResult.checked_at)
        stmt = (
            select(
                bucket.label("bucket"),
                func.percentile_cont(0.50).within_group(CheckResult.response_time_ms).label("p50"),
                func.percentile_cont(0.95).within_group(CheckResult.response_time_ms).label("p95"),
                func.percentile_cont(0.99).within_group(CheckResult.response_time_ms).label("p99"),
                func.count().label("count"),
            )
            .where(
                CheckResult.monitor_id == monitor_id,
                CheckResult.checked_at >= start,
                CheckResult.checked_at < end,
                CheckResult.response_time_ms.isnot(None),
            )
            .group_by(bucket)
        )
        return {
            row.bucket: {"p50": row.p50, "p95": row.p95, "p99": row.p99, "count": row.count}
            for row in (await db.execute(stmt)).all()
        }

    by_hour: dict[datetime, list[float]] = defaultdict(list)
    for _mid, checked_at, _status, rt, _ntype in await _fetch_check_rows(
        db, [monitor_id], start, end
    ):
        if rt is not None:
            by_hour[checked_at.replace(minute=0, second=0, microsecond=0)].append(rt)
    out = {}
    for hour, values in by_hour.items():
        ordered = sorted(values)
        out[hour] = {
            "p50": percentile_cont(ordered, 0.50),
            "p95": percentile_cont(ordered, 0.95),
            "p99": percentile_cont(ordered, 0.99),
            "count": len(ordered),
        }
    return out


async def compute_percentile_timeseries(
    db: AsyncSession,
    monitor_id: uuid.UUID,
    hours: int = 24,
) -> list[dict]:
    """P50/P95/P99 response time per hourly bucket.

    The rollup grain *is* the bucket grain here, so covered hours are read back
    verbatim — no re-aggregation, no approximation (plan V2, A-3). Only the
    hours the builder has not folded yet, including the one in progress, are
    computed from the raw table.
    """
    now = datetime.now(UTC)
    since = now - timedelta(hours=hours)
    rollup_start, rollup_end = await _rollup_window(db, since, now)

    buckets: dict[datetime, dict] = {}
    for row in await _fetch_rollup_rows(db, [monitor_id], rollup_start, rollup_end):
        if row.rt_count:
            buckets[row.bucket] = {
                "p50": row.p50_ms,
                "p95": row.p95_ms,
                "p99": row.p99_ms,
                "count": row.rt_count,
            }
    for gap_start, gap_end in _raw_gaps(since, now, rollup_start, rollup_end):
        buckets.update(await _raw_percentile_buckets(db, monitor_id, gap_start, gap_end))

    return [
        {
            "timestamp": bucket.isoformat(),
            "p50": round(values["p50"], 1) if values["p50"] else None,
            "p95": round(values["p95"], 1) if values["p95"] else None,
            "p99": round(values["p99"], 1) if values["p99"] else None,
            "count": values["count"],
        }
        for bucket, values in sorted(buckets.items())
    ]
