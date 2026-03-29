"""Maintenance window endpoints."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.api.deps import (
    build_access_filter,
    check_resource_access,
    get_current_user,
    get_user_team_ids,
)
from whatisup.core.database import get_db
from whatisup.core.limiter import limiter
from whatisup.models.maintenance import MaintenanceWindow
from whatisup.models.monitor import Monitor, MonitorGroup
from whatisup.models.user import User
from whatisup.schemas.maintenance import MaintenanceWindowCreate, MaintenanceWindowOut

router = APIRouter(prefix="/maintenance", tags=["maintenance"])


@router.get("/", response_model=list[MaintenanceWindowOut])
async def list_windows(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[MaintenanceWindow]:
    q = select(MaintenanceWindow)
    if not current_user.is_superadmin:
        team_ids = await get_user_team_ids(current_user, db)
        q = q.where(build_access_filter(MaintenanceWindow, current_user, team_ids))
    result = await db.execute(q.order_by(MaintenanceWindow.starts_at.desc()))
    return list(result.scalars().all())


@router.post("/", response_model=MaintenanceWindowOut, status_code=status.HTTP_201_CREATED)
async def create_window(
    payload: MaintenanceWindowCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MaintenanceWindow:
    if payload.monitor_id is not None and not current_user.is_superadmin:
        monitor = (
            await db.execute(
                select(Monitor).where(
                    Monitor.id == payload.monitor_id,
                    Monitor.owner_id == current_user.id,
                )
            )
        ).scalar_one_or_none()
        if monitor is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    if payload.group_id is not None and not current_user.is_superadmin:
        group = (
            await db.execute(
                select(MonitorGroup).where(
                    MonitorGroup.id == payload.group_id,
                    MonitorGroup.owner_id == current_user.id,
                )
            )
        ).scalar_one_or_none()
        if group is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    window = MaintenanceWindow(
        name=payload.name,
        description=payload.description,
        owner_id=current_user.id,
        monitor_id=payload.monitor_id,
        group_id=payload.group_id,
        starts_at=payload.starts_at,
        ends_at=payload.ends_at,
        suppress_alerts=payload.suppress_alerts,
    )
    db.add(window)
    await db.flush()
    return window


@router.delete("/{window_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("30/minute")
async def delete_window(
    request: Request,
    window_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    window = (
        await db.execute(select(MaintenanceWindow).where(MaintenanceWindow.id == window_id))
    ).scalar_one_or_none()
    if window is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Window not found")
    await check_resource_access(window, current_user, db)
    await db.delete(window)


@router.patch("/{window_id}", response_model=MaintenanceWindowOut)
@limiter.limit("30/minute")
async def update_window(
    request: Request,
    window_id: uuid.UUID,
    payload: MaintenanceWindowCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MaintenanceWindow:
    window = (
        await db.execute(select(MaintenanceWindow).where(MaintenanceWindow.id == window_id))
    ).scalar_one_or_none()
    if window is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Window not found")
    await check_resource_access(window, current_user, db)
    for field, value in payload.model_dump().items():
        setattr(window, field, value)
    await db.flush()
    return window
