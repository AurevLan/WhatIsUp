"""Custom push metrics API."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.api.deps import get_current_user, get_db
from whatisup.core.limiter import limiter
from whatisup.models.custom_metric import CustomMetric
from whatisup.models.monitor import Monitor
from whatisup.models.user import User

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/metrics", tags=["metrics"])


class MetricPush(BaseModel):
    metric_name: str = Field(..., max_length=100, pattern=r"^[a-zA-Z0-9_.\-]+$")
    value: float
    unit: str | None = Field(None, max_length=50)
    pushed_at: datetime | None = None  # default to now


class MetricOut(BaseModel):
    id: uuid.UUID
    metric_name: str
    value: float
    unit: str | None
    pushed_at: datetime

    model_config = {"from_attributes": True}


class MetricSummaryItem(BaseModel):
    metric_name: str
    unit: str | None
    min: float
    max: float
    avg: float
    last_value: float
    count: int


@router.post("/{monitor_id}", status_code=201, response_model=MetricOut)
@limiter.limit("120/minute")
async def push_metric(
    monitor_id: uuid.UUID,
    payload: MetricPush,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> CustomMetric:
    """Push a custom metric for a monitor owned by the authenticated user."""
    monitor = await db.scalar(
        select(Monitor).where(
            Monitor.id == monitor_id,
            Monitor.owner_id == current_user.id,
        )
    )
    if not monitor:
        raise HTTPException(status_code=404, detail="Moniteur introuvable")

    metric = CustomMetric(
        monitor_id=monitor_id,
        metric_name=payload.metric_name,
        value=payload.value,
        unit=payload.unit,
        pushed_at=payload.pushed_at or datetime.now(UTC),
    )
    db.add(metric)
    await db.flush()
    await db.refresh(metric)

    logger.info(
        "custom_metric_pushed",
        monitor_id=str(monitor_id),
        metric_name=payload.metric_name,
        user_id=str(current_user.id),
    )
    return metric


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
    """Return aggregated stats (min, max, avg, last value) per metric name."""
    monitor = await db.scalar(
        select(Monitor).where(
            Monitor.id == monitor_id,
            Monitor.owner_id == current_user.id,
        )
    )
    if not monitor:
        raise HTTPException(status_code=404, detail="Moniteur introuvable")

    if since is not None:
        cutoff = since.replace(tzinfo=UTC) if since.tzinfo is None else since
    else:
        cutoff = datetime.now(UTC) - timedelta(hours=min(hours, 720))

    # Aggregate by metric_name
    agg_q = (
        select(
            CustomMetric.metric_name,
            func.min(CustomMetric.value).label("min_val"),
            func.max(CustomMetric.value).label("max_val"),
            func.avg(CustomMetric.value).label("avg_val"),
            func.count(CustomMetric.id).label("cnt"),
        )
        .where(
            CustomMetric.monitor_id == monitor_id,
            CustomMetric.pushed_at >= cutoff,
        )
        .group_by(CustomMetric.metric_name)
    )
    if until is not None:
        until_tz = until.replace(tzinfo=UTC) if until.tzinfo is None else until
        agg_q = agg_q.where(CustomMetric.pushed_at <= until_tz)

    agg_result = await db.execute(agg_q)
    agg_rows = {row.metric_name: row for row in agg_result.all()}

    if not agg_rows:
        return []

    # Fetch last value per metric_name
    items = []
    for metric_name, row in agg_rows.items():
        last_q = (
            select(CustomMetric)
            .where(
                CustomMetric.monitor_id == monitor_id,
                CustomMetric.metric_name == metric_name,
                CustomMetric.pushed_at >= cutoff,
            )
            .order_by(CustomMetric.pushed_at.desc())
            .limit(1)
        )
        if until is not None:
            until_tz = until.replace(tzinfo=UTC) if until.tzinfo is None else until
            last_q = last_q.where(CustomMetric.pushed_at <= until_tz)
        last_metric = await db.scalar(last_q)

        items.append(
            MetricSummaryItem(
                metric_name=metric_name,
                unit=last_metric.unit if last_metric else None,
                min=row.min_val,
                max=row.max_val,
                avg=round(row.avg_val, 4),
                last_value=last_metric.value if last_metric else row.max_val,
                count=row.cnt,
            )
        )

    return items


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
    monitor = await db.scalar(
        select(Monitor).where(
            Monitor.id == monitor_id,
            Monitor.owner_id == current_user.id,
        )
    )
    if not monitor:
        raise HTTPException(status_code=404, detail="Moniteur introuvable")

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
