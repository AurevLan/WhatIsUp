"""Estimate how many alerts a proposed alert matrix would have fired over the last N days.

The goal is to help the user calibrate thresholds without having to wait for incidents
to happen. We replay the historical CheckResult/Incident data through each proposed
rule and return a count per condition.

This is intentionally approximate:
  - Anomaly detection uses a statistical tail estimate (normal distribution).
  - Digest/storm windows are ignored (we count raw would-fire events).
  - Per-channel dispatch is not simulated — only the rule-level decision.
"""

from __future__ import annotations

import math
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.models.incident import Incident, IncidentScope
from whatisup.models.result import CheckResult, CheckStatus

PREVIEW_WINDOW_DAYS = 30


async def compute_preview(
    db: AsyncSession,
    monitor_id: uuid.UUID,
    rows: list[dict[str, Any]],
    window_days: int = PREVIEW_WINDOW_DAYS,
) -> dict[str, Any]:
    """Return {window_days, counts: [{condition, count}]} for each proposed row."""
    now = datetime.now(UTC)
    since = now - timedelta(days=window_days)

    counts: list[dict[str, Any]] = []

    # Pre-fetch shared data used by multiple conditions
    incidents_q = select(Incident).where(
        Incident.monitor_id == monitor_id,
        Incident.started_at >= since,
        Incident.dependency_suppressed.is_(False),
    )
    incidents = list((await db.execute(incidents_q)).scalars().all())

    # Cache: count of successful check results with a non-null response time over
    # the window. Shared by anomaly_detection (tail estimate) and as a denominator
    # for any future stats — avoids re-querying when multiple rows need it.
    up_rt_samples_cache: int | None = None

    async def up_rt_samples() -> int:
        nonlocal up_rt_samples_cache
        if up_rt_samples_cache is None:
            up_rt_samples_cache = int(
                (
                    await db.execute(
                        select(func.count(CheckResult.id)).where(
                            CheckResult.monitor_id == monitor_id,
                            CheckResult.checked_at >= since,
                            CheckResult.response_time_ms.isnot(None),
                            CheckResult.status == CheckStatus.up,
                        )
                    )
                ).scalar_one()
                or 0
            )
        return up_rt_samples_cache

    def _by_min_duration(inc_list: list[Incident], min_duration: int) -> int:
        if min_duration <= 0:
            return len(inc_list)
        return sum(
            1
            for i in inc_list
            if i.duration_seconds is None or i.duration_seconds >= min_duration
        )

    for row in rows:
        condition = row.get("condition")
        min_duration = int(row.get("min_duration_seconds") or 0)
        count = 0

        if condition == "any_down":
            count = _by_min_duration(incidents, min_duration)

        elif condition == "all_down":
            globals_ = [i for i in incidents if i.scope == IncidentScope.global_]
            count = _by_min_duration(globals_, min_duration)

        elif condition == "ssl_expiry":
            # Successful HTTPS checks whose cert was within warn window in the period.
            # We count *distinct ssl check anomalies*: transitions to "warn" state.
            # Approximation: count checks where ssl_valid is False OR
            # ssl_days_remaining <= threshold (default 14 when unset).
            warn_days = int(row.get("threshold_value") or 14)
            ssl_bad = (
                await db.execute(
                    select(func.count(CheckResult.id)).where(
                        CheckResult.monitor_id == monitor_id,
                        CheckResult.checked_at >= since,
                        (
                            (CheckResult.ssl_valid.is_(False))
                            | (
                                CheckResult.ssl_days_remaining.isnot(None)
                                & (CheckResult.ssl_days_remaining <= warn_days)
                            )
                        ),
                    )
                )
            ).scalar_one()
            count = int(ssl_bad or 0)

        elif condition == "response_time_above":
            threshold = row.get("threshold_value")
            if threshold is None:
                count = 0
            else:
                rt_above = (
                    await db.execute(
                        select(func.count(CheckResult.id)).where(
                            CheckResult.monitor_id == monitor_id,
                            CheckResult.checked_at >= since,
                            CheckResult.response_time_ms.isnot(None),
                            CheckResult.response_time_ms > float(threshold),
                            CheckResult.status == CheckStatus.up,
                        )
                    )
                ).scalar_one()
                count = int(rt_above or 0)

        elif condition == "response_time_above_baseline":
            factor = float(row.get("baseline_factor") or 0)
            if factor <= 0:
                count = 0
            else:
                avg_row = (
                    await db.execute(
                        select(func.avg(CheckResult.response_time_ms)).where(
                            CheckResult.monitor_id == monitor_id,
                            CheckResult.checked_at >= since,
                            CheckResult.response_time_ms.isnot(None),
                            CheckResult.status == CheckStatus.up,
                        )
                    )
                ).scalar_one_or_none()
                if avg_row and avg_row > 0:
                    baseline_cut = float(avg_row) * factor
                    count = int(
                        (
                            await db.execute(
                                select(func.count(CheckResult.id)).where(
                                    CheckResult.monitor_id == monitor_id,
                                    CheckResult.checked_at >= since,
                                    CheckResult.response_time_ms.isnot(None),
                                    CheckResult.response_time_ms > baseline_cut,
                                    CheckResult.status == CheckStatus.up,
                                )
                            )
                        ).scalar_one()
                        or 0
                    )
                else:
                    count = 0

        elif condition == "anomaly_detection":
            # Statistical tail estimate on a normal distribution: fraction of
            # samples above the z-score threshold is ~ 0.5 * erfc(z / sqrt(2)).
            z = float(row.get("anomaly_zscore_threshold") or 3.0)
            tail_fraction = 0.5 * math.erfc(z / math.sqrt(2))
            count = int(round((await up_rt_samples()) * tail_fraction))

        elif condition == "schema_drift":
            # No historical fingerprint diff tracked — return 0 as a safe estimate.
            count = 0

        counts.append({"condition": condition, "count": count})

    return {
        "window_days": window_days,
        "counts": counts,
        "total": sum(c["count"] for c in counts),
    }
