"""External status API — for integration with third-party monitoring tools."""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.api.deps import get_current_user
from whatisup.core.database import get_db
from whatisup.core.limiter import limiter
from whatisup.models.incident import Incident
from whatisup.models.monitor import Monitor
from whatisup.models.result import CheckResult, CheckStatus
from whatisup.models.user import User
from whatisup.services.stats import compute_uptime, latest_results_subq

router = APIRouter(prefix="/status", tags=["status"])


@router.get("/monitors")
@limiter.limit("60/minute")
async def status_all_monitors(
    request: Request,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    query = select(Monitor).where(Monitor.enabled.is_(True))
    if not current_user.is_superadmin:
        query = query.where(Monitor.owner_id == current_user.id)

    monitors = (await db.execute(query.offset(offset).limit(limit))).scalars().all()
    if not monitors:
        return []

    monitor_ids = [m.id for m in monitors]

    # Batch: latest CheckResult per monitor
    latest_subq = latest_results_subq(
        CheckResult.monitor_id.in_(monitor_ids),
        group_col=CheckResult.monitor_id,
    )
    latest_results = (
        (
            await db.execute(
                select(CheckResult).join(
                    latest_subq,
                    (CheckResult.monitor_id == latest_subq.c.monitor_id)
                    & (CheckResult.checked_at == latest_subq.c.max_at),
                )
            )
        )
        .scalars()
        .all()
    )
    latest_by_monitor = {r.monitor_id: r for r in latest_results}

    # Batch: open incidents per monitor
    open_incidents = (
        (
            await db.execute(
                select(Incident).where(
                    Incident.monitor_id.in_(monitor_ids),
                    Incident.resolved_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    incident_by_monitor = {inc.monitor_id: inc for inc in open_incidents}

    results = []
    for m in monitors:
        latest = latest_by_monitor.get(m.id)
        open_incident = incident_by_monitor.get(m.id)
        results.append(
            {
                "id": str(m.id),
                "name": m.name,
                "url": m.url,
                "status": latest.status.value if latest else "unknown",
                "last_checked_at": latest.checked_at.isoformat() if latest else None,
                "response_time_ms": latest.response_time_ms if latest else None,
                "incident": {
                    "id": str(open_incident.id),
                    "scope": open_incident.scope.value,
                    "started_at": open_incident.started_at.isoformat(),
                }
                if open_incident
                else None,
            }
        )
    return results


@router.get("/monitors/{monitor_id}")
async def status_monitor(
    monitor_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    monitor = (
        await db.execute(select(Monitor).where(Monitor.id == monitor_id))
    ).scalar_one_or_none()
    if monitor is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Monitor not found")
    if not current_user.is_superadmin and monitor.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    uptime_24h = await compute_uptime(db, monitor_id, period_hours=24)
    uptime_7d = await compute_uptime(db, monitor_id, period_hours=168)

    open_incident = (
        await db.execute(
            select(Incident).where(
                Incident.monitor_id == monitor_id,
                Incident.resolved_at.is_(None),
            )
        )
    ).scalar_one_or_none()

    return {
        "id": str(monitor.id),
        "name": monitor.name,
        "url": monitor.url,
        "enabled": monitor.enabled,
        "uptime_24h_percent": uptime_24h.uptime_percent,
        "uptime_7d_percent": uptime_7d.uptime_percent,
        "avg_response_time_ms": uptime_24h.avg_response_time_ms,
        "incident": {
            "id": str(open_incident.id),
            "scope": open_incident.scope.value,
            "started_at": open_incident.started_at.isoformat(),
        }
        if open_incident
        else None,
    }


@router.get("/summary")
@limiter.limit("120/minute")
async def status_summary(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Machine-readable overall status summary.

    Returns an overall health indicator (operational / degraded / major_outage)
    plus per-monitor status. Designed for CI/CD pipelines and external integrations.
    """
    query = select(Monitor).where(Monitor.enabled.is_(True))
    if not current_user.is_superadmin:
        query = query.where(Monitor.owner_id == current_user.id)
    monitors = (await db.execute(query)).scalars().all()

    if not monitors:
        return {
            "status": "operational",
            "components": [],
            "generated_at": datetime.now(UTC).isoformat(),
        }

    monitor_ids = [m.id for m in monitors]

    # Latest result per monitor (batch)
    latest_subq = latest_results_subq(
        CheckResult.monitor_id.in_(monitor_ids),
        group_col=CheckResult.monitor_id,
    )
    latest_results = (
        await db.execute(
            select(CheckResult.monitor_id, CheckResult.status, CheckResult.response_time_ms)
            .join(
                latest_subq,
                and_(
                    CheckResult.monitor_id == latest_subq.c.monitor_id,
                    CheckResult.checked_at == latest_subq.c.max_at,
                ),
            )
        )
    ).all()
    latest_map = {r.monitor_id: r for r in latest_results}

    # Uptime 24h (batch)
    cutoff = datetime.now(UTC) - timedelta(hours=24)
    uptime_rows = (
        await db.execute(
            select(
                CheckResult.monitor_id,
                func.count(CheckResult.id).label("total"),
                func.sum(
                case((CheckResult.status == CheckStatus.up, 1), else_=0)
            ).label("up_count"),
            )
            .where(
                CheckResult.monitor_id.in_(monitor_ids),
                CheckResult.checked_at >= cutoff,
            )
            .group_by(CheckResult.monitor_id)
        )
    ).all()
    uptime_map = {
        r.monitor_id: round(r.up_count / r.total * 100, 2) for r in uptime_rows if r.total > 0
    }

    # Open incidents (batch)
    open_incidents = (
        await db.execute(
            select(Incident.monitor_id).where(
                Incident.monitor_id.in_(monitor_ids),
                Incident.resolved_at.is_(None),
            )
        )
    ).scalars().all()
    down_set = set(open_incidents)

    components = []
    for m in monitors:
        latest = latest_map.get(m.id)
        components.append({
            "id": str(m.id),
            "name": m.name,
            "check_type": m.check_type,
            "status": latest.status.value if latest else "unknown",
            "response_time_ms": latest.response_time_ms if latest else None,
            "uptime_24h_percent": uptime_map.get(m.id),
            "has_open_incident": m.id in down_set,
        })

    down_count = sum(1 for c in components if c["has_open_incident"])
    total = len(components)
    if down_count == 0:
        overall = "operational"
    elif down_count / total < 0.3:
        overall = "degraded"
    else:
        overall = "major_outage"

    return {
        "status": overall,
        "down_count": down_count,
        "total_count": total,
        "components": components,
        "generated_at": datetime.now(UTC).isoformat(),
    }
