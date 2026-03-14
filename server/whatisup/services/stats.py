"""Uptime and response time statistics service."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import case, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

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
    """Delete cached uptime entries for a monitor (called on new check result)."""
    from whatisup.core.redis import get_redis
    redis = get_redis()
    keys = [f"whatisup:uptime:{monitor_id}:24", f"whatisup:uptime:{monitor_id}:168"]
    await redis.delete(*keys)


async def compute_uptime(
    db: AsyncSession,
    monitor_id: uuid.UUID,
    period_hours: int = 24,
) -> UptimeStats:
    # Check Redis cache first (TTL 60s — balances freshness vs DB load)
    from whatisup.core.redis import get_redis
    redis = get_redis()
    cache_key = f"whatisup:uptime:{monitor_id}:{period_hours}"
    cached = await redis.get(cache_key)
    if cached:
        data = json.loads(cached)
        return UptimeStats(**data)

    cutoff = datetime.now(UTC) - timedelta(hours=period_hours)

    result = await db.execute(
        select(
            func.count(CheckResult.id).label("total"),
            func.sum(case((CheckResult.status == CheckStatus.up, 1), else_=0)).label("up_count"),
            func.avg(CheckResult.response_time_ms).label("avg_rt"),
            func.percentile_cont(0.95).within_group(
                CheckResult.response_time_ms
            ).label("p95_rt"),
        ).where(
            CheckResult.monitor_id == monitor_id,
            CheckResult.checked_at >= cutoff,
            CheckResult.response_time_ms.isnot(None),
        )
    )
    row = result.one()

    # Also get total including null response times
    count_result = await db.execute(
        select(func.count(CheckResult.id)).where(
            CheckResult.monitor_id == monitor_id,
            CheckResult.checked_at >= cutoff,
        )
    )
    total = count_result.scalar() or 0
    up_count = int(row.up_count or 0)
    avg_rt = float(row.avg_rt) if row.avg_rt is not None else None
    p95_rt = float(row.p95_rt) if row.p95_rt is not None else None

    uptime_pct = (up_count / total * 100) if total > 0 else 100.0

    stats = UptimeStats(
        monitor_id=monitor_id,
        period_hours=period_hours,
        total_checks=total,
        up_checks=up_count,
        uptime_percent=round(uptime_pct, 3),
        avg_response_time_ms=avg_rt,
        p95_response_time_ms=p95_rt,
    )

    # Store in cache (TTL 60s)
    await redis.setex(cache_key, 60, json.dumps(stats.model_dump(mode="json")))
    return stats


async def compute_daily_history(
    db: AsyncSession,
    monitor_id: uuid.UUID,
    days: int = 90,
) -> list[dict]:
    """Compute daily uptime percentage for the last N days (for history bars)."""
    cutoff = datetime.now(UTC) - timedelta(days=days)

    # text("'day'") forces a SQL literal instead of a bind param, so PostgreSQL
    # recognises GROUP BY and SELECT expressions as identical (asyncpg issue).
    day_trunc = func.date_trunc(text("'day'"), CheckResult.checked_at)
    rows = await db.execute(
        select(
            day_trunc.label("day"),
            func.count(CheckResult.id).label("total"),
            func.sum(case((CheckResult.status == CheckStatus.up, 1), else_=0)).label("up_count"),
            func.avg(CheckResult.response_time_ms).label("avg_rt"),
        )
        .where(
            CheckResult.monitor_id == monitor_id,
            CheckResult.checked_at >= cutoff,
        )
        .group_by(day_trunc)
        .order_by(day_trunc)
    )

    return [
        {
            "date": row.day.date().isoformat(),
            "total": row.total,
            "up_count": int(row.up_count or 0),
            "uptime_percent": round((int(row.up_count or 0) / row.total * 100), 2) if row.total else 100.0,
            "avg_response_time_ms": float(row.avg_rt) if row.avg_rt else None,
        }
        for row in rows.all()
    ]
