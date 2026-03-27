"""Global incidents list endpoint — cross-monitor timeline view."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.api.deps import get_current_user
from whatisup.core.database import get_db
from whatisup.core.limiter import limiter
from whatisup.models.incident import Incident
from whatisup.models.monitor import Monitor
from whatisup.models.user import User

router = APIRouter(prefix="/incidents", tags=["incidents"])


@router.get("/")
@limiter.limit("60/minute")
async def list_all_incidents(
    request: Request,
    resolved: bool | None = None,
    days: int = Query(default=30, ge=1, le=365),
    limit: int = Query(default=100, ge=1, le=500),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """List all incidents across all monitors, newest first."""
    cutoff = datetime.now(UTC) - timedelta(days=days)

    # Fetch monitors owned by user
    mon_query = select(Monitor.id, Monitor.name, Monitor.check_type)
    if not current_user.is_superadmin:
        mon_query = mon_query.where(Monitor.owner_id == current_user.id)
    monitor_rows = (await db.execute(mon_query)).all()
    monitor_ids = [r.id for r in monitor_rows]
    monitor_map = {r.id: {"name": r.name, "check_type": r.check_type} for r in monitor_rows}

    if not monitor_ids:
        return []

    query = (
        select(Incident)
        .where(
            Incident.monitor_id.in_(monitor_ids),
            Incident.started_at >= cutoff,
        )
        .order_by(Incident.started_at.desc())
        .limit(limit)
    )
    if resolved is True:
        query = query.where(Incident.resolved_at.isnot(None))
    elif resolved is False:
        query = query.where(Incident.resolved_at.is_(None))

    incidents = (await db.execute(query)).scalars().all()

    return [
        {
            "id": str(inc.id),
            "monitor_id": str(inc.monitor_id),
            "monitor_name": monitor_map.get(inc.monitor_id, {}).get("name", "—"),
            "monitor_check_type": monitor_map.get(inc.monitor_id, {}).get("check_type", ""),
            "started_at": inc.started_at.isoformat(),
            "resolved_at": inc.resolved_at.isoformat() if inc.resolved_at else None,
            "duration_seconds": inc.duration_seconds,
            "scope": inc.scope.value,
            "affected_probe_ids": inc.affected_probe_ids,
            "dependency_suppressed": inc.dependency_suppressed,
            "group_id": str(inc.group_id) if inc.group_id else None,
            "is_resolved": inc.is_resolved,
        }
        for inc in incidents
    ]
