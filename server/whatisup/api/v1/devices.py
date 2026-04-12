"""Native push device registration endpoints.

The Capacitor mobile app calls these endpoints to exchange its FCM (Android)
or APNs (iOS) registration token for a server-side row + a Fernet encryption
key. The encryption key is generated server-side, returned **once** in the
response body, and used afterwards to wrap notification payloads end-to-end
so Google's FCM relay only sees opaque ciphertext.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from cryptography.fernet import Fernet
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.api.deps import get_current_user
from whatisup.core.database import get_db
from whatisup.core.limiter import limiter
from whatisup.core.security import encrypt_channel_config
from whatisup.models.alert import AlertChannel, AlertChannelType
from whatisup.models.device_token import DevicePlatform, DeviceToken
from whatisup.models.user import User

router = APIRouter(prefix="/notifications", tags=["notifications"])


class DeviceRegisterIn(BaseModel):
    token: str
    platform: DevicePlatform = DevicePlatform.android
    label: str | None = None


class DeviceRegisterOut(BaseModel):
    id: uuid.UUID
    encryption_key: str
    platform: DevicePlatform
    label: str | None
    created: bool

    model_config = {"from_attributes": True}


class DeviceListItem(BaseModel):
    id: uuid.UUID
    platform: DevicePlatform
    label: str | None
    last_seen_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


@router.post("/devices", response_model=DeviceRegisterOut)
@limiter.limit("20/minute")
async def register_device(
    request: Request,
    payload: DeviceRegisterIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DeviceRegisterOut:
    """Register or refresh an FCM/APNs device token for the current user.

    If the token already exists for **this** user, the call is idempotent and
    just bumps last_seen_at. If the token belongs to another user (e.g. shared
    device), it gets reassigned. The encryption key is **only** returned the
    first time the token is created — subsequent calls return the existing key
    so the client can recover after reinstalling.
    """
    if not payload.token or len(payload.token) < 10:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="token is required",
        )

    existing = (
        await db.execute(select(DeviceToken).where(DeviceToken.token == payload.token))
    ).scalar_one_or_none()

    now = datetime.now(UTC)

    if existing is not None:
        existing.user_id = current_user.id
        existing.platform = payload.platform
        if payload.label is not None:
            existing.label = payload.label
        existing.last_seen_at = now
        await db.flush()
        return DeviceRegisterOut(
            id=existing.id,
            encryption_key=existing.encryption_key,
            platform=existing.platform,
            label=existing.label,
            created=False,
        )

    device = DeviceToken(
        user_id=current_user.id,
        token=payload.token,
        platform=payload.platform,
        encryption_key=Fernet.generate_key().decode(),
        label=payload.label,
        last_seen_at=now,
    )
    db.add(device)
    await db.flush()

    # Idempotently create the user's FCM alert channel so the new device
    # immediately has a destination it can be attached to in alert rules.
    existing_fcm = (
        await db.execute(
            select(AlertChannel).where(
                AlertChannel.owner_id == current_user.id,
                AlertChannel.type == AlertChannelType.fcm,
            )
        )
    ).scalar_one_or_none()
    if existing_fcm is None:
        db.add(
            AlertChannel(
                owner_id=current_user.id,
                name="Mobile push (FCM)",
                type=AlertChannelType.fcm,
                config=encrypt_channel_config({}),
            )
        )
        await db.flush()

    return DeviceRegisterOut(
        id=device.id,
        encryption_key=device.encryption_key,
        platform=device.platform,
        label=device.label,
        created=True,
    )


@router.get("/devices", response_model=list[DeviceListItem])
@limiter.limit("60/minute")
async def list_devices(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[DeviceListItem]:
    """List the current user's registered devices (no token / encryption_key)."""
    rows = (
        await db.execute(
            select(DeviceToken)
            .where(DeviceToken.user_id == current_user.id)
            .order_by(DeviceToken.last_seen_at.desc().nullslast())
        )
    ).scalars().all()
    return [DeviceListItem.model_validate(r) for r in rows]


@router.delete("/devices/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("30/minute")
async def revoke_device(
    request: Request,
    device_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Revoke a device — used when the user disables notifications or signs out."""
    result = await db.execute(
        delete(DeviceToken).where(
            DeviceToken.id == device_id,
            DeviceToken.user_id == current_user.id,
        )
    )
    if result.rowcount == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="device not found",
        )
