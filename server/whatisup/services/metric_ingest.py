"""Ingestion of pushed application metrics (plan V2, C-1).

What C-1 adds to the endpoint that already existed: **batch**, **labels** and
**quotas**. The auth was never the missing piece — a user API key (``wiu_u_*``)
could already push — but one point per request at 120/min does not carry an
agent, and a metric with no dimensions cannot answer "latency *per route*".

The two ceilings, and why they are refusals
───────────────────────────────────────────
- **Rate**, in points per minute per monitor. A sliding-window counter in Redis.
- **Cardinality**, in distinct series per monitor. Counted on ``metric_series``,
  which exists precisely so this is a ``COUNT(*)`` on a small table rather than
  a ``COUNT(DISTINCT …)`` across every monthly partition of the points table.

Both refuse with 429 rather than dropping quietly. In a monitoring product a
silently discarded metric is the worst possible failure: the graph keeps
drawing, the alert keeps not firing, and nothing anywhere says why. The same
reasoning as C-4's "silence never resolves".

A batch is **all-or-nothing**. Accepting the first half of a payload and
refusing the rest would leave the caller unable to say what it must resend, and
a partially-applied batch is indistinguishable from a lost one at the next
scrape.

Cardinality is the real hazard
──────────────────────────────
One unbounded label — a user id, a request id, a URL with an id in it — and the
row count stops being governed by how often the application pushes and starts
being governed by how many distinct values it happens to observe. Partitioning
(C-2) and retention do not help with that; only a ceiling does. The refusal names
the series that would have been created, because "cardinality exceeded" without
the offending labels is a message nobody can act on.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.core.config import get_settings
from whatisup.core.redis import get_redis
from whatisup.models.custom_metric import CustomMetric, MetricSeries, series_hash

logger = structlog.get_logger(__name__)


class QuotaExceeded(Exception):
    """A ceiling was hit. Carries what the caller needs to back off sensibly."""

    def __init__(self, detail: str, *, retry_after: int, kind: str) -> None:
        super().__init__(detail)
        self.detail = detail
        self.retry_after = retry_after
        self.kind = kind


@dataclass(frozen=True)
class IngestPoint:
    """One validated sample, ready to store."""

    metric_name: str
    value: float
    unit: str | None
    labels: dict[str, str]
    pushed_at: datetime

    @property
    def hash(self) -> str:
        return series_hash(self.metric_name, self.labels)


async def _consume_rate_budget(monitor_id: uuid.UUID, points: int, limit: int) -> None:
    """Reserve ``points`` against this monitor's per-minute budget.

    Fixed one-minute window keyed on the wall clock: two counters at most live
    at any time, and a burst can in the worst case span a window boundary. A
    sliding log would be exact and cost one Redis entry per point, which is the
    thing we are trying to avoid.

    Redis is authoritative here, so this does **not** fail open: with the
    counter unavailable there is no ceiling at all, and an ingestion endpoint
    with no ceiling is how the database fills up. It fails *closed* with a short
    retry — see ``core/redis`` on why the fail-open helpers are not used.
    """
    if limit <= 0:
        return
    now = datetime.now(UTC)
    window = now.strftime("%Y%m%d%H%M")
    key = f"whatisup:metric_quota:{monitor_id}:{window}"
    try:
        redis = get_redis()
        used = await redis.incrby(key, points)
        # Expire well past the window so a clock skew cannot resurrect a
        # counter, but short enough that idle monitors leave nothing behind.
        await redis.expire(key, 120)
    except Exception as exc:
        logger.warning("metric_quota_backend_unavailable", error=type(exc).__name__)
        raise QuotaExceeded(
            "Le compteur de quota est indisponible — réessayez dans quelques secondes.",
            retry_after=5,
            kind="backend_unavailable",
        ) from exc

    if used > limit:
        # Give the budget back so a rejected batch does not also burn the
        # window for the caller that retries correctly.
        try:
            await get_redis().decrby(key, points)
        except Exception:  # noqa: BLE001 - best effort, the TTL cleans up anyway
            pass
        raise QuotaExceeded(
            f"Quota d'ingestion dépassé pour ce moniteur : {limit} points/minute.",
            retry_after=max(1, 60 - now.second),
            kind="rate",
        )


async def _resolve_series(
    db: AsyncSession,
    monitor_id: uuid.UUID,
    points: list[IngestPoint],
    max_series: int,
) -> dict[str, MetricSeries]:
    """Return the registry rows for these points, creating what is new.

    Raises ``QuotaExceeded`` before creating anything if the batch would push
    the monitor past its cardinality ceiling.
    """
    wanted: dict[str, IngestPoint] = {p.hash: p for p in points}

    existing = {
        row.series_hash: row
        for row in (
            await db.execute(
                select(MetricSeries).where(
                    MetricSeries.monitor_id == monitor_id,
                    MetricSeries.series_hash.in_(list(wanted)),
                )
            )
        )
        .scalars()
        .all()
    }

    fresh = [p for h, p in wanted.items() if h not in existing]
    if fresh and max_series > 0:
        current = (
            await db.execute(
                select(func.count(MetricSeries.id)).where(MetricSeries.monitor_id == monitor_id)
            )
        ).scalar_one()
        if current + len(fresh) > max_series:
            sample = ", ".join(f"{p.metric_name}{_format_labels(p.labels)}" for p in fresh[:3])
            raise QuotaExceeded(
                f"Plafond de cardinalité atteint pour ce moniteur : {max_series} séries "
                f"distinctes ({current} déjà enregistrées, {len(fresh)} nouvelles refusées). "
                f"Exemple refusé : {sample}. Une étiquette à valeurs non bornées "
                "(identifiant d'utilisateur, de requête…) en est la cause habituelle.",
                retry_after=60,
                kind="cardinality",
            )

    now = datetime.now(UTC)
    for point in fresh:
        row = MetricSeries(
            monitor_id=monitor_id,
            metric_name=point.metric_name,
            labels=point.labels,
            series_hash=point.hash,
            unit=point.unit,
            first_seen_at=point.pushed_at,
            last_seen_at=point.pushed_at,
        )
        db.add(row)
        existing[point.hash] = row
    if fresh:
        await db.flush()

    # Keep the registry's view of "alive" and of the unit current. The unit is
    # a property of the series, and an application is free to correct it.
    for h, point in wanted.items():
        row = existing[h]
        pushed = point.pushed_at
        last_seen = row.last_seen_at
        if last_seen.tzinfo is None:  # SQLite hands back naive datetimes
            last_seen = last_seen.replace(tzinfo=UTC)
        if pushed > last_seen:
            row.last_seen_at = min(pushed, now)
        if point.unit is not None and point.unit != row.unit:
            row.unit = point.unit

    return existing


def _format_labels(labels: dict[str, str]) -> str:
    if not labels:
        return ""
    inner = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
    return "{" + inner + "}"


async def ingest_points(
    db: AsyncSession,
    monitor_id: uuid.UUID,
    points: list[IngestPoint],
) -> int:
    """Store a validated batch. Returns the number of points accepted.

    Order matters: the rate budget is reserved first (cheap, and the common
    rejection), then cardinality is checked against the registry, and only then
    is anything written. Nothing is inserted unless the whole batch fits.
    """
    if not points:
        return 0

    settings = get_settings()
    await _consume_rate_budget(monitor_id, len(points), settings.metrics_max_points_per_minute)
    series = await _resolve_series(db, monitor_id, points, settings.metrics_max_series_per_monitor)

    db.add_all(
        CustomMetric(
            monitor_id=monitor_id,
            metric_name=p.metric_name,
            value=p.value,
            unit=p.unit,
            labels=p.labels,
            series_hash=p.hash,
            pushed_at=p.pushed_at,
        )
        for p in points
    )
    await db.flush()

    logger.info(
        "custom_metrics_ingested",
        monitor_id=str(monitor_id),
        points=len(points),
        series=len(series),
    )
    return len(points)
