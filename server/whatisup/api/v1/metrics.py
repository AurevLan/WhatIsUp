"""Custom push metrics API."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.api.deps import check_resource_access, get_current_user, get_db
from whatisup.core.config import get_settings
from whatisup.core.limiter import limiter
from whatisup.models.custom_metric import CustomMetric, MetricSeries
from whatisup.models.monitor import Monitor
from whatisup.models.team import TeamRole
from whatisup.models.user import User
from whatisup.services.metric_ingest import IngestPoint, QuotaExceeded, ingest_points

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/metrics", tags=["metrics"])


async def _get_accessible_monitor_or_404(
    monitor_id: uuid.UUID,
    current_user: User,
    db: AsyncSession,
    min_role: TeamRole = TeamRole.viewer,
) -> Monitor:
    """Resolve the monitor with owner OR team access (same pattern as monitors.py)."""
    monitor = await db.scalar(select(Monitor).where(Monitor.id == monitor_id))
    if not monitor:
        raise HTTPException(status_code=404, detail="Moniteur introuvable")
    await check_resource_access(monitor, current_user, db, min_role=min_role)
    return monitor


_LABEL_KEY_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_.\-]*$")

#: Upper slack on ``pushed_at`` — a client's clock is allowed to run a little
#: fast, not to timestamp a point in the future.
_PUSHED_AT_MAX_FUTURE = timedelta(minutes=5)


class MetricPush(BaseModel):
    metric_name: str = Field(..., max_length=100, pattern=r"^[a-zA-Z0-9_.\-]+$")
    value: float
    unit: str | None = Field(None, max_length=50)
    #: C-1 — dimensions. Values are coerced to strings on purpose: a label is
    #: an identity, not a measurement, and letting `{"port": 8080}` and
    #: `{"port": "8080"}` be two different series is a trap, not a feature.
    labels: dict[str, str | int | float | bool] | None = None
    pushed_at: datetime | None = None  # default to now

    @field_validator("pushed_at")
    @classmethod
    def validate_pushed_at(cls, v: datetime | None) -> datetime | None:
        """Bound ``pushed_at`` to a window around *now* — reject, never clamp.

        An unbounded timestamp is not just a display glitch: ``retention.py``
        purges on ``time_col < cutoff`` and, on PostgreSQL, drops whole monthly
        partitions — a point dated far in the future skips both, lands in the
        catch-all ``DEFAULT`` partition, and stays there forever (that
        partition is never itself dropped). At up to 6000 points/min/monitor
        that is an unrecoverable leak, not a cosmetic one.

        Rejecting with a 422 rather than silently clamping to *now* or to the
        retention floor was the deliberate choice here: every other guard on
        this ingestion path (the rate quota, the cardinality quota) already
        refuses loudly instead of quietly reshaping what the caller sent — a
        clamped timestamp would let a caller believe its data landed exactly
        where it asked it to, which is precisely the kind of silent
        discrepancy C-1's quotas were built to avoid. A caller with clock
        drift gets a clear, actionable error instead of a graph that quietly
        disagrees with its own logs.

        Bounds: ``+5 min`` in the future (generous clock-drift slack, tight
        enough to catch a misconfigured client) and, when metrics retention is
        finite, ``-metrics_retention_days`` in the past — a point older than
        that would be purged on the very next nightly run, so accepting it is
        pointless work.
        """
        if v is None:
            return None
        v = v if v.tzinfo is not None else v.replace(tzinfo=UTC)
        now = datetime.now(UTC)
        if v > now + _PUSHED_AT_MAX_FUTURE:
            raise ValueError(
                f"pushed_at {v.isoformat()} is more than {_PUSHED_AT_MAX_FUTURE} in the future"
            )
        settings = get_settings()
        if settings.metrics_retention_days > 0:
            floor = now - timedelta(days=settings.metrics_retention_days)
            if v < floor:
                raise ValueError(
                    f"pushed_at {v.isoformat()} predates the metrics retention window "
                    f"({settings.metrics_retention_days} days) — it would be purged "
                    "immediately"
                )
        return v

    @field_validator("labels")
    @classmethod
    def validate_labels(cls, v: dict | None) -> dict | None:
        if not v:
            return None
        settings = get_settings()
        if len(v) > settings.metrics_max_labels_per_point:
            raise ValueError(
                f"too many labels ({len(v)} > {settings.metrics_max_labels_per_point}) — "
                "a metric carrying that many dimensions is usually an event log in disguise"
            )
        for key, value in v.items():
            if not _LABEL_KEY_RE.match(key):
                raise ValueError(
                    f"invalid label key {key!r}: must start with a letter and contain only "
                    "letters, digits, '_', '.' or '-'"
                )
            if len(key) > settings.metrics_max_label_key_length:
                raise ValueError(
                    f"label key {key!r} exceeds {settings.metrics_max_label_key_length} characters"
                )
            if len(str(value)) > settings.metrics_max_label_value_length:
                raise ValueError(
                    f"label value for {key!r} exceeds "
                    f"{settings.metrics_max_label_value_length} characters"
                )
        return {k: str(val) for k, val in v.items()}


class MetricOut(BaseModel):
    id: uuid.UUID
    metric_name: str
    value: float
    unit: str | None
    labels: dict[str, str] = Field(default_factory=dict)
    pushed_at: datetime

    model_config = {"from_attributes": True}


class MetricBatchOut(BaseModel):
    """Answer to a batch push. A batch is all-or-nothing, so this is len(payload)."""

    accepted: int


class MetricSeriesOut(BaseModel):
    metric_name: str
    labels: dict[str, str] = Field(default_factory=dict)
    unit: str | None
    first_seen_at: datetime
    last_seen_at: datetime

    model_config = {"from_attributes": True}


class MetricSummaryItem(BaseModel):
    metric_name: str
    labels: dict[str, str] = Field(default_factory=dict)
    unit: str | None
    min: float
    max: float
    avg: float
    last_value: float
    count: int


@router.post(
    "/{monitor_id}",
    status_code=201,
    response_model=None,
    responses={
        201: {"description": "Single push returns the stored point; a batch returns {accepted}."},
        429: {"description": "Rate or cardinality quota exceeded. Nothing was stored."},
    },
)
@limiter.limit("120/minute")
async def push_metric(
    monitor_id: uuid.UUID,
    payload: MetricPush | list[MetricPush],
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> MetricOut | MetricBatchOut:
    """Push one metric point, or a batch of them.

    Accepts either a single object or a list (C-1). The single-object form
    returns the stored point exactly as it did before batching existed, so
    nothing that pushes today needs to change; a list returns ``{"accepted": N}``.

    The list is **all-or-nothing**: if it would breach either quota, none of it
    is stored and the response is a 429 naming which ceiling was hit. Accepting
    half a batch would leave the caller unable to say what to resend.

    The per-IP ``120/minute`` above is a different, coarser guard than the
    per-monitor quota inside — it keeps one host from hammering the endpoint at
    all, whereas the quota bounds what a monitor may accumulate. Batching is
    what makes the two compatible: 120 requests × up to
    ``METRICS_MAX_BATCH_SIZE`` points.
    """
    await _get_accessible_monitor_or_404(monitor_id, current_user, db, min_role=TeamRole.editor)

    is_batch = isinstance(payload, list)
    items = payload if is_batch else [payload]
    if not items:
        return MetricBatchOut(accepted=0)

    settings = get_settings()
    if len(items) > settings.metrics_max_batch_size:
        raise HTTPException(
            status_code=413,
            detail=(
                f"Lot trop grand : {len(items)} points pour un maximum de "
                f"{settings.metrics_max_batch_size}."
            ),
        )

    now = datetime.now(UTC)
    points = [
        IngestPoint(
            metric_name=item.metric_name,
            value=item.value,
            unit=item.unit,
            labels=item.labels or {},
            pushed_at=item.pushed_at or now,
        )
        for item in items
    ]

    try:
        accepted = await ingest_points(db, monitor_id, points)
    except QuotaExceeded as exc:
        logger.warning(
            "custom_metric_quota_exceeded",
            monitor_id=str(monitor_id),
            kind=exc.kind,
            points=len(points),
            user_id=str(current_user.id),
        )
        raise HTTPException(
            status_code=429,
            detail=exc.detail,
            headers={"Retry-After": str(exc.retry_after)},
        ) from exc

    if is_batch:
        return MetricBatchOut(accepted=accepted)

    # Single push keeps its historical response shape: the stored point.
    stored = (
        await db.execute(
            select(CustomMetric)
            .where(
                CustomMetric.monitor_id == monitor_id,
                CustomMetric.series_hash == points[0].hash,
                CustomMetric.pushed_at == points[0].pushed_at,
            )
            .order_by(CustomMetric.pushed_at.desc())
            .limit(1)
        )
    ).scalar_one()
    return MetricOut.model_validate(stored)


# NOTE: /{monitor_id}/summary must be declared before /{monitor_id} so FastAPI
# does not greedily match "summary" as a monitor UUID.
@router.get("/{monitor_id}/summary", response_model=list[MetricSummaryItem])
@limiter.limit("60/minute")
async def get_metrics_summary(
    monitor_id: uuid.UUID,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    hours: int = 24,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[MetricSummaryItem]:
    """Aggregated stats (min, max, avg, last value) per **series**.

    Grouped by ``series_hash`` since C-1, not by name: a name can now cover
    several series, and averaging them together would report a number that
    describes nothing in particular.
    """
    await _get_accessible_monitor_or_404(monitor_id, current_user, db)

    if since is not None:
        cutoff = since.replace(tzinfo=UTC) if since.tzinfo is None else since
    else:
        cutoff = datetime.now(UTC) - timedelta(hours=min(hours, 720))
    until_tz = None
    if until is not None:
        until_tz = until.replace(tzinfo=UTC) if until.tzinfo is None else until

    window = [CustomMetric.monitor_id == monitor_id, CustomMetric.pushed_at >= cutoff]
    if until_tz is not None:
        window.append(CustomMetric.pushed_at <= until_tz)

    agg_rows = (
        await db.execute(
            select(
                CustomMetric.series_hash,
                CustomMetric.metric_name,
                func.min(CustomMetric.value).label("min_val"),
                func.max(CustomMetric.value).label("max_val"),
                func.avg(CustomMetric.value).label("avg_val"),
                func.count(CustomMetric.id).label("cnt"),
                func.max(CustomMetric.pushed_at).label("last_at"),
            )
            .where(*window)
            .group_by(CustomMetric.series_hash, CustomMetric.metric_name)
        )
    ).all()
    if not agg_rows:
        return []

    # Last value per series in one query, instead of one round-trip per series
    # as this used to do per name.
    freshest = (
        select(
            CustomMetric.series_hash.label("h"),
            func.max(CustomMetric.pushed_at).label("m"),
        )
        .where(*window)
        .group_by(CustomMetric.series_hash)
        .subquery()
    )
    last_by_hash = {
        row.series_hash: row
        for row in (
            await db.execute(
                select(
                    CustomMetric.series_hash,
                    CustomMetric.value,
                    CustomMetric.unit,
                    CustomMetric.labels,
                )
                .join(
                    freshest,
                    (CustomMetric.series_hash == freshest.c.h)
                    & (CustomMetric.pushed_at == freshest.c.m),
                )
                .where(*window)
            )
        ).all()
    }

    items = []
    for row in agg_rows:
        last = last_by_hash.get(row.series_hash)
        items.append(
            MetricSummaryItem(
                metric_name=row.metric_name,
                labels=(last.labels if last else None) or {},
                unit=last.unit if last else None,
                min=row.min_val,
                max=row.max_val,
                avg=round(row.avg_val, 4),
                last_value=last.value if last else row.max_val,
                count=row.cnt,
            )
        )
    return items


@router.get("/{monitor_id}/series", response_model=list[MetricSeriesOut])
@limiter.limit("60/minute")
async def list_metric_series(
    monitor_id: uuid.UUID,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    metric_name: str | None = None,
) -> list[MetricSeries]:
    """Every series this monitor has ever reported, from the registry (C-1).

    Read from ``metric_series`` rather than derived from the points: the answer
    then covers series that have gone quiet, which is exactly what someone
    configuring a ``metric_absent`` rule needs to see. Cheap for the same
    reason — the table is bounded by the cardinality cap, not by time.
    """
    await _get_accessible_monitor_or_404(monitor_id, current_user, db)
    stmt = select(MetricSeries).where(MetricSeries.monitor_id == monitor_id)
    if metric_name:
        stmt = stmt.where(MetricSeries.metric_name == metric_name)
    stmt = stmt.order_by(MetricSeries.metric_name, MetricSeries.series_hash)
    return list((await db.execute(stmt)).scalars().all())


@router.get("/{monitor_id}", response_model=list[MetricOut])
@limiter.limit("60/minute")
async def list_metrics(
    monitor_id: uuid.UUID,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    metric_name: str | None = None,
    hours: int = 24,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[CustomMetric]:
    """List custom metrics for a monitor over a time window (max 720h / 30 days).

    Accepts either ``since``/``until`` ISO 8601 datetime params or the legacy
    ``hours`` integer param for backwards compatibility.
    """
    await _get_accessible_monitor_or_404(monitor_id, current_user, db)

    if since is not None:
        cutoff = since.replace(tzinfo=UTC) if since.tzinfo is None else since
    else:
        cutoff = datetime.now(UTC) - timedelta(hours=min(hours, 720))

    q = (
        select(CustomMetric)
        .where(
            CustomMetric.monitor_id == monitor_id,
            CustomMetric.pushed_at >= cutoff,
        )
        .order_by(CustomMetric.pushed_at.desc())
        .limit(1000)
    )
    if until is not None:
        until_tz = until.replace(tzinfo=UTC) if until.tzinfo is None else until
        q = q.where(CustomMetric.pushed_at <= until_tz)
    if metric_name:
        q = q.where(CustomMetric.metric_name == metric_name)

    result = await db.scalars(q)
    return list(result.all())
