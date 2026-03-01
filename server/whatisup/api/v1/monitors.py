"""Monitor CRUD endpoints."""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.api.deps import get_current_user
from whatisup.core.database import get_db
from whatisup.models.monitor import Monitor
from whatisup.models.result import CheckResult, CheckStatus
from whatisup.models.tag import Tag
from whatisup.models.user import User
from whatisup.schemas.incident import IncidentOut
from whatisup.schemas.monitor import MonitorCreate, MonitorOut, MonitorUpdate
from whatisup.schemas.result import CheckResultOut, UptimeStats
from whatisup.services.stats import compute_uptime

router = APIRouter(prefix="/monitors", tags=["monitors"])


async def _get_monitor_or_404(
    monitor_id: uuid.UUID, user: User, db: AsyncSession
) -> Monitor:
    monitor = (await db.execute(
        select(Monitor).where(Monitor.id == monitor_id)
    )).scalar_one_or_none()
    if monitor is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Monitor not found")
    # Superadmin sees all; others see only their own
    if not user.is_superadmin and monitor.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    return monitor


@router.get("/", response_model=list[MonitorOut])
async def list_monitors(
    enabled: bool | None = None,
    group_id: uuid.UUID | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    query = select(Monitor)
    if not current_user.is_superadmin:
        query = query.where(Monitor.owner_id == current_user.id)
    if enabled is not None:
        query = query.where(Monitor.enabled == enabled)
    if group_id is not None:
        query = query.where(Monitor.group_id == group_id)
    monitors = list((await db.execute(query.order_by(Monitor.created_at.desc()))).scalars().all())

    if not monitors:
        return []

    monitor_ids = [m.id for m in monitors]

    # Latest status per monitor (one query — join on max checked_at)
    max_ts_subq = (
        select(
            CheckResult.monitor_id,
            func.max(CheckResult.checked_at).label("max_at"),
        )
        .where(CheckResult.monitor_id.in_(monitor_ids))
        .group_by(CheckResult.monitor_id)
        .subquery()
    )
    latest_rows = (await db.execute(
        select(CheckResult.monitor_id, CheckResult.status)
        .join(
            max_ts_subq,
            and_(
                CheckResult.monitor_id == max_ts_subq.c.monitor_id,
                CheckResult.checked_at == max_ts_subq.c.max_at,
            ),
        )
    )).all()
    latest_map = {str(r.monitor_id): r.status.value for r in latest_rows}

    # Uptime 24h per monitor (one query)
    cutoff = datetime.now(UTC) - timedelta(hours=24)
    uptime_rows = (await db.execute(
        select(
            CheckResult.monitor_id,
            func.count(CheckResult.id).label("total"),
            func.sum(case((CheckResult.status == CheckStatus.up, 1), else_=0)).label("up_count"),
        )
        .where(
            CheckResult.monitor_id.in_(monitor_ids),
            CheckResult.checked_at >= cutoff,
        )
        .group_by(CheckResult.monitor_id)
    )).all()
    uptime_map = {
        str(r.monitor_id): round(r.up_count / r.total * 100, 2)
        for r in uptime_rows
        if r.total > 0
    }

    out = []
    for m in monitors:
        mid = str(m.id)
        d = MonitorOut.model_validate(m).model_dump()
        d["last_status"] = latest_map.get(mid)
        d["uptime_24h"] = uptime_map.get(mid)
        out.append(d)
    return out


@router.post("/", response_model=MonitorOut, status_code=status.HTTP_201_CREATED)
async def create_monitor(
    payload: MonitorCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Monitor:
    tags = []
    if payload.tag_ids:
        tags_result = await db.execute(select(Tag).where(Tag.id.in_(payload.tag_ids)))
        tags = list(tags_result.scalars().all())
        if len(tags) != len(payload.tag_ids):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Some tags not found")

    monitor = Monitor(
        name=payload.name,
        url=str(payload.url),
        group_id=payload.group_id,
        owner_id=current_user.id,
        interval_seconds=payload.interval_seconds,
        timeout_seconds=payload.timeout_seconds,
        follow_redirects=payload.follow_redirects,
        expected_status_codes=payload.expected_status_codes,
        enabled=payload.enabled,
        ssl_check_enabled=payload.ssl_check_enabled,
        ssl_expiry_warn_days=payload.ssl_expiry_warn_days,
        tags=tags,
    )
    db.add(monitor)
    await db.flush()
    return monitor


@router.get("/{monitor_id}", response_model=MonitorOut)
async def get_monitor(
    monitor_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Monitor:
    return await _get_monitor_or_404(monitor_id, current_user, db)


@router.patch("/{monitor_id}", response_model=MonitorOut)
async def update_monitor(
    monitor_id: uuid.UUID,
    payload: MonitorUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Monitor:
    monitor = await _get_monitor_or_404(monitor_id, current_user, db)

    update_data = payload.model_dump(exclude_unset=True)
    tag_ids = update_data.pop("tag_ids", None)

    for field, value in update_data.items():
        if field == "url" and value is not None:
            value = str(value)
        setattr(monitor, field, value)

    if tag_ids is not None:
        tags_result = await db.execute(select(Tag).where(Tag.id.in_(tag_ids)))
        monitor.tags = list(tags_result.scalars().all())

    await db.flush()
    return monitor


@router.delete("/{monitor_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_monitor(
    monitor_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    monitor = await _get_monitor_or_404(monitor_id, current_user, db)
    await db.delete(monitor)


@router.get("/{monitor_id}/results", response_model=list[CheckResultOut])
async def get_results(
    monitor_id: uuid.UUID,
    limit: int = Query(default=100, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
    since: datetime | None = Query(default=None, description="ISO datetime — only results after this timestamp"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list:
    await _get_monitor_or_404(monitor_id, current_user, db)
    query = select(CheckResult).where(CheckResult.monitor_id == monitor_id)
    if since is not None:
        query = query.where(CheckResult.checked_at >= since)
    query = query.order_by(CheckResult.checked_at.desc()).limit(limit).offset(offset)
    result = await db.execute(query)
    return list(result.scalars().all())


@router.get("/{monitor_id}/uptime", response_model=UptimeStats)
async def get_uptime(
    monitor_id: uuid.UUID,
    period_hours: int = Query(default=24, ge=1, le=2160),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UptimeStats:
    await _get_monitor_or_404(monitor_id, current_user, db)
    return await compute_uptime(db, monitor_id, period_hours)


@router.get("/{monitor_id}/incidents", response_model=list[IncidentOut])
async def get_incidents(
    monitor_id: uuid.UUID,
    resolved: bool | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list:
    from whatisup.models.incident import Incident
    await _get_monitor_or_404(monitor_id, current_user, db)
    query = select(Incident).where(Incident.monitor_id == monitor_id)
    if resolved is True:
        query = query.where(Incident.resolved_at.isnot(None))
    elif resolved is False:
        query = query.where(Incident.resolved_at.is_(None))
    query = query.order_by(Incident.started_at.desc()).limit(limit)
    result = await db.execute(query)
    return list(result.scalars().all())
