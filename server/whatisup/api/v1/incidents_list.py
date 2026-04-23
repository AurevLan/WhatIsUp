"""Global incidents list endpoint — cross-monitor timeline view."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from whatisup.api.deps import get_current_user
from whatisup.core.database import get_db
from whatisup.core.limiter import limiter
from whatisup.models.incident import Incident, IncidentGroup
from whatisup.models.monitor import Monitor
from whatisup.models.user import User

router = APIRouter(prefix="/incidents", tags=["incidents"])


def _serialize_incident(
    inc: Incident,
    monitor_map: dict[uuid.UUID, dict],
    group_map: dict[uuid.UUID, dict],
) -> dict:
    group_info = group_map.get(inc.group_id) if inc.group_id else None
    mon = monitor_map.get(inc.monitor_id, {})
    # Runbook: only expose the markdown when the incident is still ongoing — that's
    # the only time a responder needs it, and keeps the list payload small.
    runbook_enabled = mon.get("runbook_enabled", False)
    runbook_markdown = (
        mon.get("runbook_markdown") if runbook_enabled and not inc.is_resolved else None
    )
    return {
        "id": str(inc.id),
        "monitor_id": str(inc.monitor_id),
        "monitor_name": mon.get("name", "—"),
        "monitor_check_type": mon.get("check_type", ""),
        "runbook_enabled": runbook_enabled,
        "runbook_markdown": runbook_markdown,
        "started_at": inc.started_at.isoformat(),
        "resolved_at": inc.resolved_at.isoformat() if inc.resolved_at else None,
        "duration_seconds": inc.duration_seconds,
        "scope": inc.scope.value,
        "affected_probe_ids": inc.affected_probe_ids,
        "dependency_suppressed": inc.dependency_suppressed,
        "group_id": str(inc.group_id) if inc.group_id else None,
        "acked_at": inc.acked_at.isoformat() if inc.acked_at else None,
        "acked_by_id": str(inc.acked_by_id) if inc.acked_by_id else None,
        "first_failure_at": inc.first_failure_at.isoformat() if inc.first_failure_at else None,
        "mttd_seconds": (
            max(0, int((inc.started_at - inc.first_failure_at).total_seconds()))
            if inc.first_failure_at
            else None
        ),
        "mttr_seconds": inc.duration_seconds,
        "is_resolved": inc.is_resolved,
        # Group metadata (inline)
        "correlation_type": group_info["correlation_type"] if group_info else None,
        "root_cause_monitor_name": group_info["root_cause_monitor_name"] if group_info else None,
        "group_status": group_info["status"] if group_info else None,
        "group_monitor_names": group_info["monitor_names"] if group_info else None,
    }


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
    """List all incidents across all monitors, newest first.

    Incidents that belong to a correlation group include inline group metadata
    (correlation_type, root_cause_monitor_name, sibling monitor names) so the
    frontend can render grouped incidents without a second API call.
    """
    cutoff = datetime.now(UTC) - timedelta(days=days)

    # Fetch monitors accessible by user (owned + team-based)
    mon_query = select(
        Monitor.id,
        Monitor.name,
        Monitor.check_type,
        Monitor.runbook_enabled,
        Monitor.runbook_markdown,
    )
    if not current_user.is_superadmin:
        from whatisup.api.deps import build_access_filter, get_user_team_ids

        team_ids = await get_user_team_ids(current_user, db)
        mon_query = mon_query.where(build_access_filter(Monitor, current_user, team_ids))
    monitor_rows = (await db.execute(mon_query)).all()
    monitor_ids = [r.id for r in monitor_rows]
    monitor_map = {
        r.id: {
            "name": r.name,
            "check_type": r.check_type,
            "runbook_enabled": r.runbook_enabled,
            "runbook_markdown": r.runbook_markdown,
        }
        for r in monitor_rows
    }

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

    # Batch-load group metadata for correlated incidents
    group_ids = {inc.group_id for inc in incidents if inc.group_id}
    group_map: dict[uuid.UUID, dict] = {}
    if group_ids:
        groups = (
            (
                await db.execute(
                    select(IncidentGroup)
                    .where(IncidentGroup.id.in_(group_ids))
                    .options(
                        selectinload(IncidentGroup.incidents),
                        selectinload(IncidentGroup.root_cause_monitor),
                    )
                )
            )
            .scalars()
            .all()
        )
        for g in groups:
            group_map[g.id] = {
                "correlation_type": g.correlation_type,
                "status": g.status,
                "root_cause_monitor_name": (
                    g.root_cause_monitor.name if g.root_cause_monitor else None
                ),
                "monitor_names": sorted(
                    {monitor_map.get(inc.monitor_id, {}).get("name", "?") for inc in g.incidents}
                ),
            }

    return [_serialize_incident(inc, monitor_map, group_map) for inc in incidents]
