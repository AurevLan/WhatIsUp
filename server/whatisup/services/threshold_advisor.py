"""Threshold advisor — suggests response_time thresholds based on historical data."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.models.alert import AlertCondition, AlertRule
from whatisup.models.monitor import Monitor
from whatisup.models.result import CheckResult, CheckStatus

logger = structlog.get_logger(__name__)

# Minimum data required before generating suggestions
_MIN_DATA_DAYS = 7
_SUGGESTED_HEADROOM = 1.5  # suggest threshold at p95 × 1.5


async def compute_threshold_suggestions(
    db: AsyncSession,
    owner_id: uuid.UUID | None = None,
) -> list[dict]:
    """
    For each monitor with >7 days of data and no response_time_above rule,
    compute p95 and suggest a threshold.

    Returns a list of suggestions:
      [{monitor_id, monitor_name, p95_ms, suggested_threshold_ms}]
    """
    cutoff = datetime.now(UTC) - timedelta(days=_MIN_DATA_DAYS)

    # Monitors with enough data (at least 7 days old)
    query = select(Monitor).where(
        Monitor.enabled.is_(True),
        Monitor.created_at <= cutoff,
    )
    if owner_id:
        query = query.where(Monitor.owner_id == owner_id)

    monitors = (await db.execute(query)).scalars().all()
    if not monitors:
        return []

    monitor_ids = [m.id for m in monitors]

    # Find which monitors already have a response_time_above rule
    existing_rules = (
        (
            await db.execute(
                select(AlertRule.monitor_id).where(
                    AlertRule.monitor_id.in_(monitor_ids),
                    AlertRule.condition == AlertCondition.response_time_above,
                )
            )
        )
        .scalars()
        .all()
    )
    has_rule = set(existing_rules)

    suggestions = []
    for monitor in monitors:
        if monitor.id in has_rule:
            continue

        # Compute p95 response time over the last 7 days
        p95_row = (
            await db.execute(
                select(
                    func.percentile_cont(0.95)
                    .within_group(CheckResult.response_time_ms.asc())
                    .label("p95")
                ).where(
                    CheckResult.monitor_id == monitor.id,
                    CheckResult.status == CheckStatus.up,
                    CheckResult.response_time_ms.isnot(None),
                    CheckResult.checked_at >= cutoff,
                )
            )
        ).scalar_one_or_none()

        if not p95_row or p95_row <= 0:
            continue

        suggested_ms = round(p95_row * _SUGGESTED_HEADROOM)

        suggestions.append(
            {
                "monitor_id": str(monitor.id),
                "monitor_name": monitor.name,
                "check_type": monitor.check_type,
                "p95_ms": round(p95_row),
                "suggested_threshold_ms": suggested_ms,
            }
        )

    logger.info("threshold_suggestions_computed", count=len(suggestions))
    return suggestions
