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
"""

from __future__ import annotations

import json
import uuid
from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.models.probe import NetworkType, Probe
from whatisup.models.result import CheckResult, CheckStatus
from whatisup.schemas.result import UptimeStats


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
) -> list[tuple[uuid.UUID, datetime, CheckStatus, float | None, NetworkType | None]]:
    """Fetch raw check rows joined with probe network type — used by both
    single and bulk uptime computations to keep the algorithm in one place."""
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
    rows = (await db.execute(stmt)).all()
    return [
        (r.monitor_id, r.checked_at, r.status, r.response_time_ms, r.network_type)
        for r in rows
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
    of a fixed period_hours.
    """
    stmt = (
        select(
            CheckResult.checked_at,
            CheckResult.status,
            CheckResult.response_time_ms,
            Probe.network_type,
        )
        .outerjoin(Probe, CheckResult.probe_id == Probe.id)
        .where(
            CheckResult.monitor_id == monitor_id,
            CheckResult.checked_at >= from_,
            CheckResult.checked_at <= to,
        )
    )
    raw = (await db.execute(stmt)).all()
    rows = [(r.checked_at, r.status, r.response_time_ms, r.network_type) for r in raw]
    internal_pct, external_pct, total, up, avg_rt, p95_rt = _aggregate_consensus(rows)

    rt_values = [r.response_time_ms for r in raw if r.response_time_ms is not None]
    min_rt = min(rt_values) if rt_values else None
    max_rt = max(rt_values) if rt_values else None

    return {
        "total_checks": total,
        "up_checks": up,
        "uptime_percent": round(_global_uptime(internal_pct, external_pct), 4),
        "internal_uptime_percent": internal_pct,
        "external_uptime_percent": external_pct,
        "avg_response_time_ms": round(avg_rt, 1) if avg_rt is not None else None,
        "p95_response_time_ms": round(p95_rt, 1) if p95_rt is not None else None,
        "min_response_time_ms": round(min_rt, 1) if min_rt is not None else None,
        "max_response_time_ms": round(max_rt, 1) if max_rt is not None else None,
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
        internal_pct, external_pct, _total, _up, _avg, _p95 = _aggregate_consensus(monitor_rows)
        out[str(mid)] = {
            "uptime_percent": round(_global_uptime(internal_pct, external_pct), 2),
            "internal_uptime_percent": internal_pct,
            "external_uptime_percent": external_pct,
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
    cutoff = datetime.now(UTC) - timedelta(days=days)
    rows = await _fetch_check_rows(db, [monitor_id], cutoff)

    by_day: dict[
        datetime,
        list[tuple[datetime, CheckStatus, float | None, NetworkType | None]],
    ] = defaultdict(list)
    for _, checked_at, status, rt, ntype in rows:
        day = checked_at.replace(hour=0, minute=0, second=0, microsecond=0)
        by_day[day].append((checked_at, status, rt, ntype))

    out: list[dict] = []
    for day in sorted(by_day):
        day_rows = by_day[day]
        internal_pct, external_pct, total, up, avg_rt, _p95 = _aggregate_consensus(day_rows)
        out.append(
            {
                "date": day.date().isoformat(),
                "total": total,
                "up_count": up,
                "uptime_percent": round(_global_uptime(internal_pct, external_pct), 2),
                "internal_uptime_percent": internal_pct,
                "external_uptime_percent": external_pct,
                "avg_response_time_ms": round(avg_rt, 1) if avg_rt is not None else None,
            }
        )
    return out


async def compute_percentile_timeseries(
    db: AsyncSession,
    monitor_id: uuid.UUID,
    hours: int = 24,
) -> list[dict]:
    """Compute P50/P95/P99 response time per time bucket."""
    since = datetime.now(UTC) - timedelta(hours=hours)

    bucket = func.date_trunc(text("'hour'"), CheckResult.checked_at)

    stmt = (
        select(
            bucket.label("bucket"),
            func.percentile_cont(0.50)
            .within_group(CheckResult.response_time_ms)
            .label("p50"),
            func.percentile_cont(0.95)
            .within_group(CheckResult.response_time_ms)
            .label("p95"),
            func.percentile_cont(0.99)
            .within_group(CheckResult.response_time_ms)
            .label("p99"),
            func.count().label("count"),
        )
        .where(
            CheckResult.monitor_id == monitor_id,
            CheckResult.checked_at >= since,
            CheckResult.response_time_ms.isnot(None),
        )
        .group_by(bucket)
        .order_by(bucket)
    )

    rows = (await db.execute(stmt)).all()
    return [
        {
            "timestamp": row.bucket.isoformat(),
            "p50": round(row.p50, 1) if row.p50 else None,
            "p95": round(row.p95, 1) if row.p95 else None,
            "p99": round(row.p99, 1) if row.p99 else None,
            "count": row.count,
        }
        for row in rows
    ]
