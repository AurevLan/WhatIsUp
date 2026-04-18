"""Incident update endpoints — timeline of status updates posted on an incident."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.api.deps import get_current_user
from whatisup.core.database import get_db
from whatisup.core.limiter import limiter
from whatisup.models.incident import Incident
from whatisup.models.incident_update import IncidentUpdate
from whatisup.models.monitor import Monitor
from whatisup.models.user import User
from whatisup.schemas.incident import IncidentOut, IncidentUpdateCreate, IncidentUpdateOut

router = APIRouter(prefix="/incidents", tags=["incidents"])


async def _get_incident_for_user(
    incident_id: uuid.UUID,
    current_user: User,
    db: AsyncSession,
) -> Incident:
    """Fetch incident and verify the current user owns the monitor it belongs to."""
    incident = (
        await db.execute(select(Incident).where(Incident.id == incident_id))
    ).scalar_one_or_none()
    if incident is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incident not found")

    if not current_user.is_superadmin:
        from whatisup.api.deps import check_resource_access

        monitor = (
            await db.execute(
                select(Monitor).where(Monitor.id == incident.monitor_id)
            )
        ).scalar_one_or_none()
        if monitor is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Monitor not found")
        await check_resource_access(monitor, current_user, db)

    return incident


@router.get("/{incident_id}/updates", response_model=list[IncidentUpdateOut])
@limiter.limit("60/minute")
async def list_incident_updates(
    request: Request,
    incident_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list:
    await _get_incident_for_user(incident_id, current_user, db)
    updates = (
        await db.execute(
            select(IncidentUpdate)
            .where(IncidentUpdate.incident_id == incident_id)
            .order_by(IncidentUpdate.created_at.asc())
        )
    ).scalars().all()
    return list(updates)


@router.post("/{incident_id}/updates", response_model=IncidentUpdateOut, status_code=201)
@limiter.limit("30/minute")
async def create_incident_update(
    request: Request,
    incident_id: uuid.UUID,
    body: IncidentUpdateCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> IncidentUpdate:
    await _get_incident_for_user(incident_id, current_user, db)

    update = IncidentUpdate(
        incident_id=incident_id,
        created_by_id=current_user.id,
        created_by_name=current_user.email,
        status=body.status,
        message=body.message,
        is_public=body.is_public,
        created_at=datetime.now(UTC),
    )
    db.add(update)
    await db.flush()
    await db.refresh(update)
    return update


@router.delete("/{incident_id}/updates/{update_id}", status_code=204)
@limiter.limit("30/minute")
async def delete_incident_update(
    request: Request,
    incident_id: uuid.UUID,
    update_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await _get_incident_for_user(incident_id, current_user, db)

    update = (
        await db.execute(
            select(IncidentUpdate).where(
                IncidentUpdate.id == update_id,
                IncidentUpdate.incident_id == incident_id,
            )
        )
    ).scalar_one_or_none()
    if update is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Update not found")

    await db.delete(update)


@router.post("/{incident_id}/ack", response_model=IncidentOut)
@limiter.limit("30/minute")
async def acknowledge_incident(
    request: Request,
    incident_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Incident:
    incident = await _get_incident_for_user(incident_id, current_user, db)
    if incident.resolved_at is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot ack a resolved incident"
        )
    incident.acked_at = datetime.now(UTC)
    incident.acked_by_id = current_user.id
    await db.flush()
    return _incident_to_out(incident)


@router.post("/{incident_id}/unack", response_model=IncidentOut)
@limiter.limit("30/minute")
async def unacknowledge_incident(
    request: Request,
    incident_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Incident:
    incident = await _get_incident_for_user(incident_id, current_user, db)
    incident.acked_at = None
    incident.acked_by_id = None
    await db.flush()
    return _incident_to_out(incident)


def _incident_to_out(inc: Incident) -> dict:
    """Build IncidentOut-compatible dict with computed SLA metrics."""
    mttd = None
    if inc.first_failure_at and inc.started_at:
        mttd = max(0, int((inc.started_at - inc.first_failure_at).total_seconds()))
    return {
        "id": inc.id,
        "monitor_id": inc.monitor_id,
        "started_at": inc.started_at,
        "resolved_at": inc.resolved_at,
        "duration_seconds": inc.duration_seconds,
        "scope": inc.scope,
        "affected_probe_ids": inc.affected_probe_ids,
        "dependency_suppressed": inc.dependency_suppressed,
        "group_id": inc.group_id,
        "acked_at": inc.acked_at,
        "acked_by_id": inc.acked_by_id,
        "first_failure_at": inc.first_failure_at,
        "mttd_seconds": mttd,
        "mttr_seconds": inc.duration_seconds,
    }
