"""Alert channel endpoints — CRUD, test, Telegram bot resolution."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.api.deps import (
    assert_can_assign_team,
    build_access_filter,
    check_resource_access,
    get_current_user,
    get_user_team_ids,
)
from whatisup.core.database import get_db
from whatisup.core.limiter import limiter
from whatisup.core.security import encrypt_channel_config
from whatisup.models.alert import AlertChannel
from whatisup.models.team import TeamRole
from whatisup.models.user import User
from whatisup.schemas.alert import (
    AlertChannelCreate,
    AlertChannelOut,
    AlertChannelTestOut,
    TelegramResolveIn,
    TelegramResolveOut,
)
from whatisup.services.alert import test_channel

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("/channels", response_model=list[AlertChannelOut])
@limiter.limit("60/minute")
async def list_channels(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[AlertChannel]:
    query = select(AlertChannel)
    if not current_user.is_superadmin:
        team_ids = await get_user_team_ids(current_user, db)
        query = query.where(build_access_filter(AlertChannel, current_user, team_ids))
    result = await db.execute(query)
    return list(result.scalars().all())


@router.post("/channels", response_model=AlertChannelOut, status_code=status.HTTP_201_CREATED)
@limiter.limit("30/minute")
async def create_channel(
    payload: AlertChannelCreate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AlertChannel:
    # SEC-A3: a user must not attach a channel to a team they cannot access.
    await assert_can_assign_team(db, current_user, payload.team_id)
    channel = AlertChannel(
        owner_id=current_user.id,
        team_id=payload.team_id,
        name=payload.name,
        type=payload.type,
        config=encrypt_channel_config(payload.config),
        webhook_template=payload.webhook_template,
    )
    db.add(channel)
    await db.flush()
    from whatisup.services.audit import log_action

    await log_action(
        db,
        "alert_channel.create",
        "alert_channel",
        channel.id,
        channel.name,
        current_user,
        diff={"type": channel.type.value if hasattr(channel.type, "value") else str(channel.type)},
    )
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
        await db.execute(select(AlertChannel).where(AlertChannel.id == channel_id))
    ).scalar_one_or_none()
    if channel is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Channel not found")
    await check_resource_access(channel, current_user, db)
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
    import re

    import httpx

    token = payload.bot_token.strip()
    # Validate token format to prevent SSRF via crafted token values
    # Telegram tokens: numeric bot ID (up to 20 digits) + ":" + alphanumeric secret (35-50 chars)
    if len(token) > 100 or not re.fullmatch(r"[0-9]{1,20}:[A-Za-z0-9_-]{1,80}", token):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Telegram bot token format (expected 123456:ABC-DEF…).",
        )
    base_url = f"https://api.telegram.org/bot{token}"

    async with httpx.AsyncClient(timeout=10) as client:
        try:
            resp = await client.get(f"{base_url}/getUpdates", params={"limit": 10, "offset": -10})
            resp.raise_for_status()
        except httpx.HTTPError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Telegram API error: could not reach the bot API.",
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
                    "Could not extract a chat from bot updates — send a text message to your bot."
                ),
            )

        chat = msg["chat"]
        chat_id = str(chat["id"])
        chat_name = (
            chat.get("title")
            or " ".join(filter(None, [chat.get("first_name"), chat.get("last_name")]))
            or chat.get("username")
            or chat_id
        )

        # Send validation message
        try:
            val_resp = await client.post(
                f"{base_url}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": (
                        "✅ <b>WhatIsUp</b> — bot connected successfully! Alerts will be sent here."
                    ),
                    "parse_mode": "HTML",
                },
            )
            val_resp.raise_for_status()
        except httpx.HTTPError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Could not send validation message.",
            )

    return TelegramResolveOut(chat_id=chat_id, chat_name=chat_name)


@router.delete("/channels/{channel_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("30/minute")
async def delete_channel(
    request: Request,
    channel_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    channel = (
        await db.execute(select(AlertChannel).where(AlertChannel.id == channel_id))
    ).scalar_one_or_none()
    if channel is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Channel not found")
    try:
        await check_resource_access(channel, current_user, db, min_role=TeamRole.admin)
    except HTTPException as exc:
        if exc.status_code == status.HTTP_403_FORBIDDEN:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Channel not found"
            ) from None
        raise
    from whatisup.services.audit import log_action

    await log_action(
        db,
        "alert_channel.delete",
        "alert_channel",
        channel.id,
        channel.name,
        current_user,
    )
    await db.delete(channel)
