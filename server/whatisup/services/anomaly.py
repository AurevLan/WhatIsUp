"""Anomaly detection — z-score based response time analysis."""

from __future__ import annotations

import math
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import extract, select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.models.result import CheckResult, CheckStatus


async def compute_zscore(
    db: AsyncSession,
    monitor_id: uuid.UUID,
    current_value: float,
    window_days: int = 7,
    hour_bucket_width: int = 2,
) -> float | None:
    """
    Compute the z-score of `current_value` against recent samples for the same
    monitor, filtered to the same ±`hour_bucket_width` hour window of the day.

    Returns None when there are fewer than 10 data points (not enough history).
    """
    now = datetime.now(UTC)
    since = now - timedelta(days=window_days)

    current_hour = now.hour
    hour_low = (current_hour - hour_bucket_width) % 24
    hour_high = (current_hour + hour_bucket_width) % 24

    hour_col = extract("hour", CheckResult.checked_at)
    if hour_low <= hour_high:
        # Normal range, e.g. hours 10-14
        hour_filter = hour_col.between(hour_low, hour_high)
    else:
        # Wraps around midnight, e.g. hours 22-2
        hour_filter = (hour_col >= hour_low) | (hour_col <= hour_high)

    rows = (
        await db.execute(
            select(CheckResult.response_time_ms)
            .where(
                CheckResult.monitor_id == monitor_id,
                CheckResult.checked_at >= since,
                CheckResult.status == CheckStatus.up,
                CheckResult.response_time_ms.is_not(None),
                hour_filter,
            )
            .order_by(CheckResult.checked_at.desc())
            .limit(500)
        )
    ).scalars().all()

    samples = [v for v in rows if v is not None]

    if len(samples) < 10:
        return None

    mean = sum(samples) / len(samples)
    variance = sum((x - mean) ** 2 for x in samples) / len(samples)
    stddev = math.sqrt(variance)

    if stddev == 0:
        return 0.0

    return (current_value - mean) / stddev


async def is_anomaly(
    db: AsyncSession,
    monitor_id: uuid.UUID,
    response_time_ms: float,
    zscore_threshold: float = 3.0,
) -> tuple[bool, float | None]:
    """
    Returns (is_anomaly, zscore).
    is_anomaly is False when there isn't enough history.
    """
    zscore = await compute_zscore(db, monitor_id, response_time_ms)
    if zscore is None:
        return False, None
    return zscore > zscore_threshold, zscore
