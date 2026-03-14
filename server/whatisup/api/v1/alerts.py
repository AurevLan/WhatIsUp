"""Alert channel and rule endpoints."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from whatisup.api.deps import get_current_user
from whatisup.core.database import get_db
from whatisup.core.security import decrypt_channel_config, encrypt_channel_config
from whatisup.models.alert import AlertChannel, AlertEvent, AlertRule
from whatisup.models.user import User
from whatisup.schemas.alert import (
    AlertChannelCreate,
    AlertChannelOut,
    AlertEventOut,
    AlertRuleCreate,
    AlertRuleOut,
)

router = APIRouter(prefix="/alerts", tags=["alerts"])


# ── Channels ──────────────────────────────────────────────────────────────

@router.get("/channels", response_model=list[AlertChannelOut])
async def list_channels(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[AlertChannel]:
    result = await db.execute(
        select(AlertChannel).where(AlertChannel.owner_id == current_user.id)
    )
    return list(result.scalars().all())


@router.post("/channels", response_model=AlertChannelOut, status_code=status.HTTP_201_CREATED)
async def create_channel(
    payload: AlertChannelCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AlertChannel:
    channel = AlertChannel(
        owner_id=current_user.id,
        name=payload.name,
        type=payload.type,
        config=encrypt_channel_config(payload.config),
    )
    db.add(channel)
    await db.flush()
    return channel


@router.delete("/channels/{channel_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_channel(
    channel_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    channel = (await db.execute(
        select(AlertChannel).where(
            AlertChannel.id == channel_id, AlertChannel.owner_id == current_user.id
        )
    )).scalar_one_or_none()
    if channel is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Channel not found")
    await db.delete(channel)


# ── Rules ─────────────────────────────────────────────────────────────────

@router.get("/rules", response_model=list[AlertRuleOut])
async def list_rules(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[AlertRule]:
    result = await db.execute(
        select(AlertRule)
        .join(AlertRule.channels)
        .where(AlertChannel.owner_id == current_user.id)
        .distinct()
        .options(selectinload(AlertRule.channels))
    )
    return list(result.scalars().all())


@router.post("/rules", response_model=AlertRuleOut, status_code=status.HTTP_201_CREATED)
async def create_rule(
    payload: AlertRuleCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AlertRule:
    if payload.monitor_id is None and payload.group_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either monitor_id or group_id must be specified",
        )

    channels_result = await db.execute(
        select(AlertChannel).where(
            AlertChannel.id.in_(payload.channel_ids),
            AlertChannel.owner_id == current_user.id,
        )
    )
    channels = list(channels_result.scalars().all())
    if len(channels) != len(payload.channel_ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Some channels not found"
        )

    rule = AlertRule(
        monitor_id=payload.monitor_id,
        group_id=payload.group_id,
        condition=payload.condition,
        min_duration_seconds=payload.min_duration_seconds,
        renotify_after_minutes=payload.renotify_after_minutes,
        threshold_value=payload.threshold_value,
        digest_minutes=payload.digest_minutes,
        channels=channels,
    )
    db.add(rule)
    await db.flush()
    await db.refresh(rule, ["channels"])
    return rule


@router.delete("/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule(
    rule_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    # Verify ownership via channels (a rule belongs to the user if at least one channel is theirs)
    rule = (await db.execute(
        select(AlertRule)
        .join(AlertRule.channels)
        .where(AlertRule.id == rule_id, AlertChannel.owner_id == current_user.id)
        .options(selectinload(AlertRule.channels))
    )).scalar_one_or_none()
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")
    await db.delete(rule)


# ── Events ────────────────────────────────────────────────────────────────

@router.get("/events", response_model=list[AlertEventOut])
async def list_events(
    limit: int = Query(default=50, ge=1, le=500),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[AlertEvent]:
    # Only return events for channels owned by this user
    result = await db.execute(
        select(AlertEvent)
        .join(AlertChannel, AlertEvent.channel_id == AlertChannel.id)
        .where(AlertChannel.owner_id == current_user.id)
        .order_by(AlertEvent.sent_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())
