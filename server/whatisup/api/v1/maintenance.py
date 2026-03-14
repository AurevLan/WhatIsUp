"""Maintenance window endpoints."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.api.deps import get_current_user
from whatisup.core.database import get_db
from whatisup.models.maintenance import MaintenanceWindow
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
        q = q.where(MaintenanceWindow.owner_id == current_user.id)
    result = await db.execute(q.order_by(MaintenanceWindow.starts_at.desc()))
    return list(result.scalars().all())


@router.post("/", response_model=MaintenanceWindowOut, status_code=status.HTTP_201_CREATED)
async def create_window(
    payload: MaintenanceWindowCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MaintenanceWindow:
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
async def delete_window(
    window_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    window = (
        await db.execute(select(MaintenanceWindow).where(MaintenanceWindow.id == window_id))
    ).scalar_one_or_none()
    if window is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Window not found")
    if not current_user.is_superadmin and window.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    await db.delete(window)


@router.patch("/{window_id}", response_model=MaintenanceWindowOut)
async def update_window(
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
    if not current_user.is_superadmin and window.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    for field, value in payload.model_dump().items():
        setattr(window, field, value)
    await db.flush()
    return window
