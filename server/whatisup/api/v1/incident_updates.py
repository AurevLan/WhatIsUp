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
from whatisup.schemas.incident import IncidentUpdateCreate, IncidentUpdateOut

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
        monitor = (
            await db.execute(
                select(Monitor).where(
                    Monitor.id == incident.monitor_id,
                    Monitor.owner_id == current_user.id,
                )
            )
        ).scalar_one_or_none()
        if monitor is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

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
    await db.commit()
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
    await db.commit()
