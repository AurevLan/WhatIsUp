"""Monitor statistics — results, uptime, history, percentiles, probe status, SLA report."""

import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.api.deps import (
    get_current_user,
    require_superadmin,
)
from whatisup.api.v1.monitors._common import _get_monitor_or_404
from whatisup.core.database import get_db
from whatisup.core.limiter import limiter
from whatisup.models.probe import Probe
from whatisup.models.result import CheckResult
from whatisup.models.user import User
from whatisup.schemas.probe import ProbeMonitorStatus
from whatisup.schemas.result import CheckResultOut, UptimeStats
from whatisup.services.stats import (
    compute_uptime,
    compute_uptime_in_range,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/monitors", tags=["monitors"])


@router.get("/{monitor_id}/results", response_model=list[CheckResultOut])
@limiter.limit("120/minute")
async def get_results(
    request: Request,
    monitor_id: uuid.UUID,
    limit: int = Query(default=100, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
    since: datetime | None = Query(
        default=None, description="ISO datetime — only results after this timestamp"
    ),
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
@limiter.limit("60/minute")
async def get_uptime(
    request: Request,
    monitor_id: uuid.UUID,
    period_hours: int = Query(default=24, ge=1, le=2160),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UptimeStats:
    await _get_monitor_or_404(monitor_id, current_user, db)
    return await compute_uptime(db, monitor_id, period_hours)


@router.get("/{monitor_id}/history", response_model=list[dict])
@limiter.limit("60/minute")
async def get_history(
    request: Request,
    monitor_id: uuid.UUID,
    days: int = Query(default=90, ge=1, le=365),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Daily uptime history for the last N days (for history bars UI)."""
    await _get_monitor_or_404(monitor_id, current_user, db)
    from whatisup.services.stats import compute_daily_history

    return await compute_daily_history(db, monitor_id, days)


@router.get("/{monitor_id}/percentiles")
@limiter.limit("60/minute")
async def get_percentiles(
    monitor_id: uuid.UUID,
    request: Request,
    hours: int = Query(default=24, ge=1, le=720),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """P50/P95/P99 response time percentiles over time buckets."""
    await _get_monitor_or_404(monitor_id, current_user, db)
    from whatisup.services.stats import compute_percentile_timeseries

    return await compute_percentile_timeseries(db, monitor_id, hours=hours)


@router.get("/{monitor_id}/probes", response_model=list[ProbeMonitorStatus])
@limiter.limit("60/minute")
async def get_monitor_probe_status(
    request: Request,
    monitor_id: uuid.UUID,
    _user: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Last check result per probe for a given monitor."""
    # Subquery: MAX(checked_at) per probe_id for this monitor
    max_ts_subq = (
        select(
            CheckResult.probe_id,
            func.max(CheckResult.checked_at).label("max_at"),
        )
        .where(CheckResult.monitor_id == monitor_id)
        .group_by(CheckResult.probe_id)
        .subquery()
    )

    # Latest result row per probe
    latest_rows = (
        await db.execute(
            select(
                CheckResult.probe_id,
                CheckResult.status,
                CheckResult.checked_at,
                CheckResult.response_time_ms,
            ).join(
                max_ts_subq,
                and_(
                    CheckResult.probe_id == max_ts_subq.c.probe_id,
                    CheckResult.checked_at == max_ts_subq.c.max_at,
                    CheckResult.monitor_id == monitor_id,
                ),
            )
        )
    ).all()
    latest_map = {str(r.probe_id): r for r in latest_rows}

    # All probes
    probes = list((await db.execute(select(Probe).order_by(Probe.name))).scalars().all())

    out = []
    for p in probes:
        row = latest_map.get(str(p.id))
        out.append(
            ProbeMonitorStatus(
                probe_id=p.id,
                name=p.name,
                location_name=p.location_name,
                latitude=p.latitude,
                longitude=p.longitude,
                is_active=p.is_active,
                last_seen_at=p.last_seen_at,
                last_status=row.status if row else None,
                last_checked_at=row.checked_at if row else None,
                response_time_ms=row.response_time_ms if row else None,
            )
        )
    return out


@router.get("/{monitor_id}/report")
@limiter.limit("20/minute")
async def get_sla_report(
    request: Request,
    monitor_id: uuid.UUID,
    from_: datetime = Query(alias="from", description="ISO datetime start"),
    to: datetime = Query(default=None, description="ISO datetime end (default: now)"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """SLA report for a custom date range."""
    await _get_monitor_or_404(monitor_id, current_user, db)
    if to is None:
        to = datetime.now(UTC)

    consensus = await compute_uptime_in_range(db, monitor_id, from_, to)

    # Count incidents in period
    from whatisup.models.incident import Incident

    inc_result = await db.execute(
        select(
            func.count(Incident.id).label("count"),
            func.sum(Incident.duration_seconds).label("total_downtime"),
        ).where(
            Incident.monitor_id == monitor_id,
            Incident.started_at >= from_,
            Incident.started_at <= to,
        )
    )
    inc_row = inc_result.one()

    return {
        "monitor_id": str(monitor_id),
        "from": from_.isoformat(),
        "to": to.isoformat(),
        **consensus,
        "incident_count": int(inc_row.count or 0),
        "total_downtime_seconds": int(inc_row.total_downtime or 0),
    }
