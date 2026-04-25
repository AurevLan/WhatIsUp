"""Alert silence endpoints (T1-01) — time-bounded mute of alert dispatch."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.api.deps import check_resource_access, get_current_user
from whatisup.core.database import get_db
from whatisup.core.limiter import limiter
from whatisup.models.monitor import Monitor
from whatisup.models.silence import AlertSilence
from whatisup.models.user import User
from whatisup.schemas.silence import AlertSilenceCreate, AlertSilenceOut, AlertSilenceUpdate

router = APIRouter(prefix="/silences", tags=["silences"])


async def _get_owned_silence(
    silence_id: uuid.UUID,
    current_user: User,
    db: AsyncSession,
) -> AlertSilence:
    silence = (
        await db.execute(select(AlertSilence).where(AlertSilence.id == silence_id))
    ).scalar_one_or_none()
    if silence is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Silence not found")
    if silence.owner_id != current_user.id and not current_user.is_superadmin:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Silence not found")
    return silence


@router.get("/", response_model=list[AlertSilenceOut])
@limiter.limit("60/minute")
async def list_silences(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[AlertSilence]:
    rows = (
        await db.execute(
            select(AlertSilence)
            .where(AlertSilence.owner_id == current_user.id)
            .order_by(AlertSilence.starts_at.desc())
        )
    ).scalars().all()
    return list(rows)


@router.post("/", response_model=AlertSilenceOut, status_code=status.HTTP_201_CREATED)
@limiter.limit("20/minute")
async def create_silence(
    request: Request,
    payload: AlertSilenceCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AlertSilence:
    if payload.monitor_id is not None:
        monitor = (
            await db.execute(select(Monitor).where(Monitor.id == payload.monitor_id))
        ).scalar_one_or_none()
        if monitor is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Monitor not found"
            )
        if not current_user.is_superadmin:
            await check_resource_access(monitor, current_user, db)

    silence = AlertSilence(
        name=payload.name,
        reason=payload.reason,
        owner_id=current_user.id,
        monitor_id=payload.monitor_id,
        starts_at=payload.starts_at,
        ends_at=payload.ends_at,
    )
    db.add(silence)
    await db.flush()
    await db.refresh(silence)
    return silence


@router.patch("/{silence_id}", response_model=AlertSilenceOut)
@limiter.limit("30/minute")
async def update_silence(
    request: Request,
    silence_id: uuid.UUID,
    payload: AlertSilenceUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AlertSilence:
    silence = await _get_owned_silence(silence_id, current_user, db)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(silence, field, value)
    if silence.ends_at <= silence.starts_at:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="ends_at must be after starts_at",
        )
    await db.flush()
    return silence


@router.delete("/{silence_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("30/minute")
async def delete_silence(
    request: Request,
    silence_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    silence = await _get_owned_silence(silence_id, current_user, db)
    await db.delete(silence)
