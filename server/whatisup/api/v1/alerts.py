"""Alert channel and rule endpoints."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from whatisup.api.deps import get_current_user
from whatisup.core.database import get_db
from whatisup.core.limiter import limiter
from whatisup.core.security import encrypt_channel_config
from whatisup.models.alert import AlertChannel, AlertEvent, AlertRule
from whatisup.models.incident import Incident
from whatisup.models.monitor import Monitor, MonitorGroup
from whatisup.models.user import User
from whatisup.schemas.alert import (
    AlertChannelCreate,
    AlertChannelOut,
    AlertChannelTestOut,
    AlertEventOut,
    AlertRuleCreate,
    AlertRuleOut,
    AlertRuleSimulateOut,
    AlertRuleUpdate,
    TelegramResolveIn,
    TelegramResolveOut,
)
from whatisup.services.alert import simulate_rule, test_channel

router = APIRouter(prefix="/alerts", tags=["alerts"])


# ── Channels ──────────────────────────────────────────────────────────────


@router.get("/channels", response_model=list[AlertChannelOut])
async def list_channels(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[AlertChannel]:
    result = await db.execute(select(AlertChannel).where(AlertChannel.owner_id == current_user.id))
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


@router.post("/channels/{channel_id}/test", response_model=AlertChannelTestOut)
@limiter.limit("10/minute")
async def test_channel_endpoint(
    channel_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AlertChannelTestOut:
    channel = (
        await db.execute(
            select(AlertChannel).where(
                AlertChannel.id == channel_id, AlertChannel.owner_id == current_user.id
            )
        )
    ).scalar_one_or_none()
    if channel is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Channel not found")
    success, detail = await test_channel(channel)
    return AlertChannelTestOut(success=success, detail=detail)


@router.post("/telegram/resolve", response_model=TelegramResolveOut)
@limiter.limit("10/minute")
async def telegram_resolve(
    payload: TelegramResolveIn,
    request: Request,
    current_user: User = Depends(get_current_user),
) -> TelegramResolveOut:
    """Fetch the latest chat_id from a bot token via getUpdates, then send a validation message."""
    import httpx

    token = payload.bot_token.strip()
    base_url = f"https://api.telegram.org/bot{token}"

    async with httpx.AsyncClient(timeout=10) as client:
        try:
            resp = await client.get(f"{base_url}/getUpdates", params={"limit": 10, "offset": -10})
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Telegram API error: {exc}",
            )

        data = resp.json()
        if not data.get("ok"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=data.get("description", "Invalid bot token"),
            )

        updates = data.get("result", [])
        if not updates:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No messages received yet — send any message to your bot first, then retry.",
            )

        # Pick the most recent chat
        last_update = updates[-1]
        msg = last_update.get("message") or last_update.get("channel_post")
        if not msg:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=(
                    "Could not extract a chat from bot updates"
                    " — send a text message to your bot."
                ),
            )

        chat = msg["chat"]
        chat_id = str(chat["id"])
        chat_name = chat.get("title") or " ".join(
            filter(None, [chat.get("first_name"), chat.get("last_name")])
        ) or chat.get("username") or chat_id

        # Send validation message
        try:
            val_resp = await client.post(
                f"{base_url}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": (
                        "✅ <b>WhatIsUp</b> — bot connected successfully!"
                        " Alerts will be sent here."
                    ),
                    "parse_mode": "HTML",
                },
            )
            val_resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Could not send validation message: {exc}",
            )

    return TelegramResolveOut(chat_id=chat_id, chat_name=chat_name)


@router.delete("/channels/{channel_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_channel(
    channel_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    channel = (
        await db.execute(
            select(AlertChannel).where(
                AlertChannel.id == channel_id, AlertChannel.owner_id == current_user.id
            )
        )
    ).scalar_one_or_none()
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
        .where(AlertRule.channels.any(AlertChannel.owner_id == current_user.id))
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

    if payload.monitor_id is not None:
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

    if payload.group_id is not None:
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
        storm_window_seconds=payload.storm_window_seconds,
        storm_max_alerts=payload.storm_max_alerts,
        baseline_factor=payload.baseline_factor,
        channels=channels,
    )
    db.add(rule)
    await db.flush()
    await db.refresh(rule, ["channels"])
    return rule


@router.patch("/rules/{rule_id}", response_model=AlertRuleOut)
async def update_rule(
    rule_id: uuid.UUID,
    payload: AlertRuleUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AlertRule:
    rule = (
        await db.execute(
            select(AlertRule)
            .join(AlertRule.channels)
            .where(AlertRule.id == rule_id, AlertChannel.owner_id == current_user.id)
            .options(selectinload(AlertRule.channels))
        )
    ).scalar_one_or_none()
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")

    if payload.enabled is not None:
        rule.enabled = payload.enabled
    if payload.condition is not None:
        rule.condition = payload.condition
    if payload.min_duration_seconds is not None:
        rule.min_duration_seconds = payload.min_duration_seconds
    if payload.renotify_after_minutes is not None:
        rule.renotify_after_minutes = payload.renotify_after_minutes
    if payload.threshold_value is not None:
        rule.threshold_value = payload.threshold_value
    if payload.digest_minutes is not None:
        rule.digest_minutes = payload.digest_minutes
    if payload.storm_window_seconds is not None:
        rule.storm_window_seconds = payload.storm_window_seconds
    if payload.storm_max_alerts is not None:
        rule.storm_max_alerts = payload.storm_max_alerts
    if payload.baseline_factor is not None:
        rule.baseline_factor = payload.baseline_factor

    if payload.channel_ids is not None:
        channels_result = await db.execute(
            select(AlertChannel).where(
                AlertChannel.id.in_(payload.channel_ids),
                AlertChannel.owner_id == current_user.id,
            )
        )
        new_channels = list(channels_result.scalars().all())
        if len(new_channels) != len(payload.channel_ids):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Some channels not found"
            )
        rule.channels = new_channels

    await db.flush()
    await db.refresh(rule, ["channels"])
    return rule


@router.post("/rules/{rule_id}/simulate", response_model=AlertRuleSimulateOut)
@limiter.limit("20/minute")
async def simulate_rule_endpoint(
    rule_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AlertRuleSimulateOut:
    rule = (
        await db.execute(
            select(AlertRule)
            .join(AlertRule.channels)
            .where(AlertRule.id == rule_id, AlertChannel.owner_id == current_user.id)
            .options(selectinload(AlertRule.channels))
        )
    ).scalar_one_or_none()
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")
    result = await simulate_rule(db, rule)
    return AlertRuleSimulateOut(**result)


@router.delete("/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule(
    rule_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    # Verify ownership via the associated monitor or group.
    # Using channel membership was fragile: a rule with zero channels became un-deletable.
    rule = (
        await db.execute(
            select(AlertRule)
            .outerjoin(Monitor, AlertRule.monitor_id == Monitor.id)
            .outerjoin(MonitorGroup, AlertRule.group_id == MonitorGroup.id)
            .where(
                AlertRule.id == rule_id,
                or_(
                    Monitor.owner_id == current_user.id,
                    MonitorGroup.owner_id == current_user.id,
                )
                if not current_user.is_superadmin
                else AlertRule.id == rule_id,
            )
        )
    ).scalar_one_or_none()
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")
    await db.delete(rule)


# ── Events ────────────────────────────────────────────────────────────────


@router.get("/events", response_model=list[AlertEventOut])
async def list_events(
    limit: int = Query(default=50, ge=1, le=500),
    status_filter: str | None = Query(default=None, alias="status"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[AlertEventOut]:
    from whatisup.models.alert import AlertEventStatus

    stmt = (
        select(AlertEvent, Monitor.name.label("monitor_name"))
        .join(AlertChannel, AlertEvent.channel_id == AlertChannel.id)
        .join(Incident, AlertEvent.incident_id == Incident.id)
        .outerjoin(Monitor, Incident.monitor_id == Monitor.id)
        .where(AlertChannel.owner_id == current_user.id)
        .order_by(AlertEvent.sent_at.desc())
        .limit(limit)
    )

    if status_filter in ("sent", "failed"):
        stmt = stmt.where(AlertEvent.status == AlertEventStatus(status_filter))

    rows = (await db.execute(stmt)).all()

    return [
        AlertEventOut(
            id=event.id,
            incident_id=event.incident_id,
            channel_id=event.channel_id,
            sent_at=event.sent_at,
            status=event.status,
            monitor_name=monitor_name,
            response_body=event.response_body,
        )
        for event, monitor_name in rows
    ]
