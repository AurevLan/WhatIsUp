"""Custom push metrics API."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
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
        pushed_at=payload.pushed_at or datetime.now(timezone.utc),
    )
    db.add(metric)
    await db.commit()
    await db.refresh(metric)

    logger.info(
        "custom_metric_pushed",
        monitor_id=str(monitor_id),
        metric_name=payload.metric_name,
        user_id=str(current_user.id),
    )
    return metric


@router.get("/{monitor_id}", response_model=list[MetricOut])
@limiter.limit("60/minute")
async def list_metrics(
    monitor_id: uuid.UUID,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    metric_name: str | None = None,
    hours: int = 24,
) -> list[CustomMetric]:
    """List custom metrics for a monitor over a time window (max 720h / 30 days)."""
    monitor = await db.scalar(
        select(Monitor).where(
            Monitor.id == monitor_id,
            Monitor.owner_id == current_user.id,
        )
    )
    if not monitor:
        raise HTTPException(status_code=404, detail="Moniteur introuvable")

    cutoff = datetime.now(timezone.utc) - timedelta(hours=min(hours, 720))
    q = (
        select(CustomMetric)
        .where(
            CustomMetric.monitor_id == monitor_id,
            CustomMetric.pushed_at >= cutoff,
        )
        .order_by(CustomMetric.pushed_at.desc())
        .limit(1000)
    )
    if metric_name:
        q = q.where(CustomMetric.metric_name == metric_name)

    result = await db.scalars(q)
    return list(result.all())
