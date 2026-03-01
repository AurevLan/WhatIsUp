"""External status API — for integration with third-party monitoring tools."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.api.deps import get_current_user
from whatisup.core.database import get_db
from whatisup.models.incident import Incident
from whatisup.models.monitor import Monitor
from whatisup.models.result import CheckResult
from whatisup.models.user import User
from whatisup.services.stats import compute_uptime

router = APIRouter(prefix="/status", tags=["status"])


@router.get("/monitors")
async def status_all_monitors(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    query = select(Monitor).where(Monitor.enabled is True)
    if not current_user.is_superadmin:
        query = query.where(Monitor.owner_id == current_user.id)

    monitors = (await db.execute(query)).scalars().all()
    results = []
    for m in monitors:
        latest = (await db.execute(
            select(CheckResult)
            .where(CheckResult.monitor_id == m.id)
            .order_by(CheckResult.checked_at.desc())
            .limit(1)
        )).scalar_one_or_none()

        open_incident = (await db.execute(
            select(Incident).where(
                Incident.monitor_id == m.id,
                Incident.resolved_at.is_(None),
            )
        )).scalar_one_or_none()

        results.append({
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
            } if open_incident else None,
        })
    return results


@router.get("/monitors/{monitor_id}")
async def status_monitor(
    monitor_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    monitor = (await db.execute(
        select(Monitor).where(Monitor.id == monitor_id)
    )).scalar_one_or_none()
    if monitor is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Monitor not found")
    if not current_user.is_superadmin and monitor.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    uptime_24h = await compute_uptime(db, monitor_id, period_hours=24)
    uptime_7d = await compute_uptime(db, monitor_id, period_hours=168)

    open_incident = (await db.execute(
        select(Incident).where(
            Incident.monitor_id == monitor_id,
            Incident.resolved_at.is_(None),
        )
    )).scalar_one_or_none()

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
        } if open_incident else None,
    }
