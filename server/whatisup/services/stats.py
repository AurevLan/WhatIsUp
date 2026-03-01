"""Uptime and response time statistics service."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.models.result import CheckResult, CheckStatus
from whatisup.schemas.result import UptimeStats


async def compute_uptime(
    db: AsyncSession,
    monitor_id: uuid.UUID,
    period_hours: int = 24,
) -> UptimeStats:
    cutoff = datetime.now(UTC) - timedelta(hours=period_hours)

    result = await db.execute(
        select(
            func.count(CheckResult.id).label("total"),
            func.sum(case((CheckResult.status == CheckStatus.up, 1), else_=0)).label("up_count"),
            func.avg(CheckResult.response_time_ms).label("avg_rt"),
        ).where(
            CheckResult.monitor_id == monitor_id,
            CheckResult.checked_at >= cutoff,
        )
    )
    row = result.one()
    total = row.total or 0
    up_count = int(row.up_count or 0)
    avg_rt = float(row.avg_rt) if row.avg_rt is not None else None

    # p95 response time
    p95_rt = None
    if total > 0:
        p95_result = await db.execute(
            select(CheckResult.response_time_ms)
            .where(
                CheckResult.monitor_id == monitor_id,
                CheckResult.checked_at >= cutoff,
                CheckResult.response_time_ms.isnot(None),
            )
            .order_by(CheckResult.response_time_ms)
        )
        rts = [r[0] for r in p95_result.all()]
        if rts:
            idx = int(len(rts) * 0.95)
            p95_rt = rts[min(idx, len(rts) - 1)]

    uptime_pct = (up_count / total * 100) if total > 0 else 100.0

    return UptimeStats(
        monitor_id=monitor_id,
        period_hours=period_hours,
        total_checks=total,
        up_checks=up_count,
        uptime_percent=round(uptime_pct, 3),
        avg_response_time_ms=avg_rt,
        p95_response_time_ms=p95_rt,
    )
