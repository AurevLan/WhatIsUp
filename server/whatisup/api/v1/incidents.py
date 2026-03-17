"""Incident & IncidentGroup endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from whatisup.api.deps import get_current_user
from whatisup.core.database import get_db
from whatisup.core.limiter import limiter
from whatisup.models.incident import Incident, IncidentGroup
from whatisup.models.monitor import Monitor
from whatisup.models.user import User
from whatisup.schemas.incident import IncidentGroupOut

router = APIRouter(prefix="/incident-groups", tags=["incidents"])


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
        .options(selectinload(IncidentGroup.incidents))
        .order_by(IncidentGroup.triggered_at.desc())
        .limit(limit)
    )
    if status_filter:
        query = query.where(IncidentGroup.status == status_filter)

    groups = (await db.execute(query)).scalars().all()

    # Filter: only return groups that contain at least one incident owned by the user
    # (or all if superadmin)
    if not current_user.is_superadmin:
        owned_monitor_ids = set(
            (
                await db.execute(
                    select(Monitor.id).where(Monitor.owner_id == current_user.id)
                )
            ).scalars().all()
        )
        groups = [
            g for g in groups if any(inc.monitor_id in owned_monitor_ids for inc in g.incidents)
        ]

    result = []
    for g in groups:
        d = IncidentGroupOut(
            id=g.id,
            triggered_at=g.triggered_at,
            resolved_at=g.resolved_at,
            cause_probe_ids=g.cause_probe_ids,
            status=g.status,
            incident_ids=[inc.id for inc in g.incidents],
        )
        result.append(d)
    return result


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
            .options(selectinload(IncidentGroup.incidents))
        )
    ).scalar_one_or_none()
    if group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")

    # Ownership check for non-superadmins
    if not current_user.is_superadmin:
        owned_monitor_ids = set(
            (
                await db.execute(
                    select(Monitor.id).where(Monitor.owner_id == current_user.id)
                )
            ).scalars().all()
        )
        if not any(inc.monitor_id in owned_monitor_ids for inc in group.incidents):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    return IncidentGroupOut(
        id=group.id,
        triggered_at=group.triggered_at,
        resolved_at=group.resolved_at,
        cause_probe_ids=group.cause_probe_ids,
        status=group.status,
        incident_ids=[inc.id for inc in group.incidents],
    )
