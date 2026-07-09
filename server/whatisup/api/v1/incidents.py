"""Incident & IncidentGroup endpoints.

Tenant scoping (finding SA7 — REST twin of the WS finding SA5): correlation
groups span tenants (correlation runs globally on shared probes), so both the
access gate AND the serialized payload must be scoped to the requester:

* access gate: a user sees a group only if it contains at least one incident
  on a monitor they can access (owner OR team, via ``build_access_filter`` —
  ``owner_id``-only checks would hide team-shared monitors and diverge from
  the rest of the API);
* payload rewrite: ``incident_ids`` / ``incident_refs`` are filtered to the
  requester's accessible monitors, and ``root_cause_monitor_id`` /
  ``root_cause_monitor_name`` are nulled when the root-cause monitor belongs
  to another tenant. Keys stay present (values filtered) so the frontend
  contract is unchanged. Superadmins receive the full payload.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from whatisup.api.deps import build_access_filter, get_current_user, get_user_team_ids
from whatisup.core.database import get_db
from whatisup.core.limiter import limiter
from whatisup.models.incident import IncidentGroup
from whatisup.models.monitor import Monitor
from whatisup.models.user import User
from whatisup.schemas.incident import IncidentGroupOut, IncidentRef

router = APIRouter(prefix="/incident-groups", tags=["incidents"])


async def _accessible_monitor_ids(db: AsyncSession, user: User) -> set[uuid.UUID] | None:
    """Monitor ids the user may see (owner OR team), or ``None`` for superadmin.

    ``None`` means "unrestricted": superadmins skip the access filter entirely
    and receive full cross-tenant payloads.
    """
    if user.is_superadmin:
        return None
    team_ids = await get_user_team_ids(user, db)
    rows = await db.execute(select(Monitor.id).where(build_access_filter(Monitor, user, team_ids)))
    return set(rows.scalars().all())


def _serialize_group(group: IncidentGroup, accessible: set[uuid.UUID] | None) -> IncidentGroupOut:
    """Build the scoped ``IncidentGroupOut`` payload for one requester.

    ``accessible is None`` (superadmin) keeps the full payload; otherwise every
    monitor-derived field is filtered to the requester's scope — values are
    filtered/nulled, keys never removed, so the response shape stays stable.
    """
    incidents = group.incidents
    root_cause_visible = group.root_cause_monitor_id is not None
    if accessible is not None:
        incidents = [inc for inc in incidents if inc.monitor_id in accessible]
        root_cause_visible = (
            group.root_cause_monitor_id is not None and group.root_cause_monitor_id in accessible
        )
    return IncidentGroupOut(
        id=group.id,
        triggered_at=group.triggered_at,
        resolved_at=group.resolved_at,
        cause_probe_ids=group.cause_probe_ids,
        status=group.status,
        root_cause_monitor_id=(group.root_cause_monitor_id if root_cause_visible else None),
        root_cause_monitor_name=(
            group.root_cause_monitor.name
            if root_cause_visible and group.root_cause_monitor
            else None
        ),
        correlation_type=group.correlation_type,
        incident_ids=[inc.id for inc in incidents],
        incident_refs=[IncidentRef(id=inc.id, monitor_id=inc.monitor_id) for inc in incidents],
    )


@router.get("/", response_model=list[IncidentGroupOut])
@limiter.limit("60/minute")
async def list_incident_groups(
    request: Request,
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list:
    """List correlation groups. Each group aggregates incidents caused by the same probes."""
    query = (
        select(IncidentGroup)
        .options(
            selectinload(IncidentGroup.incidents),
            selectinload(IncidentGroup.root_cause_monitor),
        )
        .order_by(IncidentGroup.triggered_at.desc())
        .limit(limit)
    )
    if status_filter:
        query = query.where(IncidentGroup.status == status_filter)

    groups = (await db.execute(query)).scalars().all()

    # Access gate (SA7): only groups containing at least one incident on a
    # monitor within the requester's scope (owner OR team). Superadmin sees all.
    accessible = await _accessible_monitor_ids(db, current_user)
    if accessible is not None:
        groups = [g for g in groups if any(inc.monitor_id in accessible for inc in g.incidents)]

    return [_serialize_group(g, accessible) for g in groups]


@router.get("/{group_id}", response_model=IncidentGroupOut)
@limiter.limit("60/minute")
async def get_incident_group(
    request: Request,
    group_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> IncidentGroupOut:
    group = (
        await db.execute(
            select(IncidentGroup)
            .where(IncidentGroup.id == group_id)
            .options(
                selectinload(IncidentGroup.incidents),
                selectinload(IncidentGroup.root_cause_monitor),
            )
        )
    ).scalar_one_or_none()
    if group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")

    # Access gate (SA7) — owner OR team via build_access_filter, not owner_id alone.
    accessible = await _accessible_monitor_ids(db, current_user)
    if accessible is not None and not any(inc.monitor_id in accessible for inc in group.incidents):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    return _serialize_group(group, accessible)
