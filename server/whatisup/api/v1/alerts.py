"""Alert channel and rule endpoints."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from whatisup.api.deps import (
    build_access_filter,
    check_resource_access,
    get_current_user,
    get_user_team_ids,
    require_superadmin,
)
from whatisup.core.database import get_db
from whatisup.core.limiter import limiter
from whatisup.core.security import encrypt_channel_config
from whatisup.models.alert import AlertChannel, AlertCondition, AlertEvent, AlertRule
from whatisup.models.alert_matrix_template import AlertMatrixTemplate
from whatisup.models.incident import Incident
from whatisup.models.monitor import Monitor, MonitorGroup
from whatisup.models.team import TeamRole
from whatisup.models.user import User
from whatisup.schemas.alert import (
    AlertChannelCreate,
    AlertChannelOut,
    AlertChannelTestOut,
    AlertEventOut,
    AlertMatrixIn,
    AlertMatrixOut,
    AlertRuleCreate,
    AlertRuleOut,
    AlertRuleSimulateOut,
    AlertRuleUpdate,
    TelegramResolveIn,
    TelegramResolveOut,
)
from whatisup.schemas.alert_matrix_template import (
    AlertMatrixTemplateIn,
    AlertMatrixTemplateOut,
    AlertMatrixTemplateUpdate,
)
from whatisup.services.alert import simulate_rule, test_channel
from whatisup.services.alert_presets import get_presets
from whatisup.services.threshold_advisor import compute_threshold_suggestions

router = APIRouter(prefix="/alerts", tags=["alerts"])


async def _fetch_channels_by_ids(
    db: AsyncSession,
    user: User,
    channel_ids: list[uuid.UUID] | set[uuid.UUID],
) -> list[AlertChannel]:
    """Return user-visible channels for all requested ids, or raise 400 on any miss.

    Honours team sharing via `build_access_filter` — `owner_id`-only checks would
    silently drop channels shared through a team.
    """
    ids = list(channel_ids)
    if not ids:
        return []
    query = select(AlertChannel).where(AlertChannel.id.in_(ids))
    if not user.is_superadmin:
        team_ids = await get_user_team_ids(user, db)
        query = query.where(build_access_filter(AlertChannel, user, team_ids))
    result = await db.execute(query)
    channels = list(result.scalars().all())
    if len(channels) != len({*ids}):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Some channels not found"
        )
    return channels


# ── Channels ──────────────────────────────────────────────────────────────


@router.get("/channels", response_model=list[AlertChannelOut])
async def list_channels(
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
async def create_channel(
    payload: AlertChannelCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AlertChannel:
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
    await db.delete(channel)


# ── Rules ─────────────────────────────────────────────────────────────────


@router.get("/rules", response_model=list[AlertRuleOut])
async def list_rules(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[AlertRule]:
    query = select(AlertRule).options(selectinload(AlertRule.channels))
    if not current_user.is_superadmin:
        team_ids = await get_user_team_ids(current_user, db)
        # Rules visible if user owns the target monitor/group or is in the team
        query = (
            query.outerjoin(Monitor, AlertRule.monitor_id == Monitor.id)
            .outerjoin(MonitorGroup, AlertRule.group_id == MonitorGroup.id)
            .where(
                or_(
                    build_access_filter(Monitor, current_user, team_ids),
                    build_access_filter(MonitorGroup, current_user, team_ids),
                )
            )
        )
    result = await db.execute(query)
    return list(result.unique().scalars().all())


@router.post("/rules", response_model=AlertRuleOut, status_code=status.HTTP_201_CREATED)
async def create_rule(
    payload: AlertRuleCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AlertRule:
    if payload.monitor_id is None and payload.group_id is None and not payload.tag_selector:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Specify monitor_id, group_id, or tag_selector",
        )

    if payload.monitor_id is not None:
        monitor = (
            await db.execute(select(Monitor).where(Monitor.id == payload.monitor_id))
        ).scalar_one_or_none()
        if monitor is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Monitor not found")
        await check_resource_access(monitor, current_user, db, min_role=TeamRole.editor)

    if payload.group_id is not None:
        group = (
            await db.execute(select(MonitorGroup).where(MonitorGroup.id == payload.group_id))
        ).scalar_one_or_none()
        if group is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")
        await check_resource_access(group, current_user, db, min_role=TeamRole.editor)

    channels = await _fetch_channels_by_ids(db, current_user, payload.channel_ids)

    rule = AlertRule(
        owner_id=current_user.id,
        monitor_id=payload.monitor_id,
        group_id=payload.group_id,
        tag_selector=payload.tag_selector,
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


async def _load_rule_for_owner(rule_id: uuid.UUID, user: User, db: AsyncSession) -> AlertRule:
    """Load a rule and verify the caller owns it.

    Since v1.2.1 alert_rules.owner_id is NOT NULL (migration a0b1c2d3e4f5),
    so ownership is a simple uuid comparison — the legacy monitor/group
    fallback path has been removed.
    """
    rule = (
        await db.execute(
            select(AlertRule)
            .where(AlertRule.id == rule_id)
            .options(selectinload(AlertRule.channels))
        )
    ).scalar_one_or_none()
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")

    if user.is_superadmin or rule.owner_id == user.id:
        return rule
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")


@router.patch("/rules/{rule_id}", response_model=AlertRuleOut)
@limiter.limit("30/minute")
async def update_rule(
    request: Request,
    rule_id: uuid.UUID,
    payload: AlertRuleUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AlertRule:
    rule = await _load_rule_for_owner(rule_id, current_user, db)

    if payload.enabled is not None:
        rule.enabled = payload.enabled
    if payload.condition is not None:
        rule.condition = payload.condition
    if payload.tag_selector is not None:
        rule.tag_selector = payload.tag_selector or None
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
        rule.channels = await _fetch_channels_by_ids(db, current_user, payload.channel_ids)

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
    rule = await _load_rule_for_owner(rule_id, current_user, db)
    result = await simulate_rule(db, rule)
    return AlertRuleSimulateOut(**result)


@router.delete("/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("30/minute")
async def delete_rule(
    request: Request,
    rule_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    rule = await _load_rule_for_owner(rule_id, current_user, db)
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
        .order_by(AlertEvent.sent_at.desc())
        .limit(limit)
    )

    if not current_user.is_superadmin:
        team_ids = await get_user_team_ids(current_user, db)
        stmt = stmt.where(build_access_filter(AlertChannel, current_user, team_ids))

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


# ── Presets ──────────────────────────────────────────────────────────────


@router.get("/presets/{check_type}")
async def get_alert_presets(
    check_type: str,
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    """Return recommended alert rule presets for a given check type."""
    return get_presets(check_type)


@router.post("/auto-rules/{monitor_id}", response_model=list[AlertRuleOut])
@limiter.limit("10/minute")
async def create_auto_rules(
    monitor_id: uuid.UUID,
    request: Request,
    channel_ids: list[uuid.UUID] | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[AlertRule]:
    """Create recommended alert rules for a monitor based on its check_type.

    Only creates rules marked as default=True in the presets.
    If no channel_ids provided, uses all channels owned by the user.
    """
    monitor = (
        await db.execute(
            select(Monitor).where(
                Monitor.id == monitor_id,
                Monitor.owner_id == current_user.id,
            )
        )
    ).scalar_one_or_none()
    if monitor is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Monitor not found")

    # Get channels
    if channel_ids:
        channels = list(
            (
                await db.execute(
                    select(AlertChannel).where(
                        AlertChannel.id.in_(channel_ids),
                        AlertChannel.owner_id == current_user.id,
                    )
                )
            )
            .scalars()
            .all()
        )
    else:
        channels = list(
            (await db.execute(select(AlertChannel).where(AlertChannel.owner_id == current_user.id)))
            .scalars()
            .all()
        )

    if not channels:
        return []

    # Check existing rules to avoid duplicates
    existing_rules = (
        (await db.execute(select(AlertRule.condition).where(AlertRule.monitor_id == monitor_id)))
        .scalars()
        .all()
    )
    existing_conditions = set(existing_rules)

    presets = get_presets(monitor.check_type)
    created: list[AlertRule] = []

    for preset in presets:
        if not preset.get("default", False):
            continue
        if preset["condition"] in existing_conditions:
            continue

        rule = AlertRule(
            owner_id=current_user.id,
            monitor_id=monitor_id,
            condition=preset["condition"],
            min_duration_seconds=preset.get("min_duration_seconds", 0),
            threshold_value=preset.get("threshold_value"),
            channels=channels,
        )
        db.add(rule)
        created.append(rule)

    if created:
        await db.flush()
        for rule in created:
            await db.refresh(rule, ["channels"])

    return created


# ── Matrix (conditions × channels per monitor) ──────────────────────────


_MATRIX_RULE_FIELDS = (
    "enabled",
    "min_duration_seconds",
    "renotify_after_minutes",
    "threshold_value",
    "digest_minutes",
    "storm_window_seconds",
    "storm_max_alerts",
    "baseline_factor",
    "anomaly_zscore_threshold",
    "schedule",
)


async def _load_monitor_with_rules(
    monitor_id: uuid.UUID,
    user: User,
    db: AsyncSession,
    min_role: TeamRole = TeamRole.viewer,
) -> Monitor:
    monitor = (
        await db.execute(
            select(Monitor)
            .where(Monitor.id == monitor_id)
            .options(selectinload(Monitor.alert_rules).selectinload(AlertRule.channels))
        )
    ).scalar_one_or_none()
    if monitor is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Monitor not found")
    await check_resource_access(monitor, user, db, min_role=min_role)
    return monitor


@router.post("/monitors/{monitor_id}/matrix/preview")
@limiter.limit("60/minute")
async def preview_alert_matrix(
    monitor_id: uuid.UUID,
    payload: AlertMatrixIn,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Simulate how many alerts the proposed matrix would have fired over the last 30 days."""
    from whatisup.services.alert_matrix_preview import compute_preview

    await _load_monitor_with_rules(monitor_id, current_user, db)
    rows = [r.model_dump() for r in payload.rows]
    return await compute_preview(db, monitor_id, rows)


@router.get("/matrix-templates/{check_type}", response_model=list[AlertMatrixTemplateOut])
async def list_matrix_templates(
    check_type: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[AlertMatrixTemplate]:
    """Return all alert matrix templates for a given check_type."""
    result = await db.execute(
        select(AlertMatrixTemplate)
        .where(AlertMatrixTemplate.check_type == check_type)
        .order_by(AlertMatrixTemplate.is_system.desc(), AlertMatrixTemplate.name)
    )
    return list(result.scalars().all())


@router.post(
    "/matrix-templates", response_model=AlertMatrixTemplateOut, status_code=status.HTTP_201_CREATED
)
@limiter.limit("30/minute")
async def create_matrix_template(
    payload: AlertMatrixTemplateIn,
    request: Request,
    current_user: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> AlertMatrixTemplate:
    tpl = AlertMatrixTemplate(
        name=payload.name,
        description=payload.description,
        check_type=payload.check_type,
        rows=payload.rows,
        is_system=False,
    )
    db.add(tpl)
    await db.flush()
    return tpl


@router.patch("/matrix-templates/{template_id}", response_model=AlertMatrixTemplateOut)
@limiter.limit("30/minute")
async def update_matrix_template(
    template_id: uuid.UUID,
    payload: AlertMatrixTemplateUpdate,
    request: Request,
    current_user: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> AlertMatrixTemplate:
    tpl = (
        await db.execute(select(AlertMatrixTemplate).where(AlertMatrixTemplate.id == template_id))
    ).scalar_one_or_none()
    if tpl is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(tpl, field, value)
    await db.flush()
    return tpl


@router.delete("/matrix-templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("30/minute")
async def delete_matrix_template(
    template_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> None:
    tpl = (
        await db.execute(select(AlertMatrixTemplate).where(AlertMatrixTemplate.id == template_id))
    ).scalar_one_or_none()
    if tpl is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
    if tpl.is_system:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="System templates cannot be deleted",
        )
    await db.delete(tpl)


@router.get("/monitors/{monitor_id}/matrix", response_model=AlertMatrixOut)
async def get_alert_matrix(
    monitor_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AlertMatrixOut:
    monitor = await _load_monitor_with_rules(monitor_id, current_user, db)
    return AlertMatrixOut(monitor_id=monitor_id, rows=monitor.alert_rules)


@router.put("/monitors/{monitor_id}/matrix", response_model=AlertMatrixOut)
@limiter.limit("30/minute")
async def put_alert_matrix(
    monitor_id: uuid.UUID,
    payload: AlertMatrixIn,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AlertMatrixOut:
    """Upsert a monitor's alert rules from a matrix payload.

    One row per condition; rows absent from the payload are deleted.
    """
    monitor = await _load_monitor_with_rules(monitor_id, current_user, db, min_role=TeamRole.editor)

    seen_conditions: set[AlertCondition] = set()
    for row in payload.rows:
        if row.condition in seen_conditions:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Duplicate condition in payload: {row.condition}",
            )
        seen_conditions.add(row.condition)
        if not row.channel_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Row {row.condition} has no channel",
            )

    all_channel_ids = {cid for row in payload.rows for cid in row.channel_ids}
    fetched = await _fetch_channels_by_ids(db, current_user, all_channel_ids)
    channels_by_id: dict[uuid.UUID, AlertChannel] = {c.id: c for c in fetched}

    existing_by_condition: dict[AlertCondition, AlertRule] = {
        r.condition: r for r in monitor.alert_rules
    }

    for condition, rule in existing_by_condition.items():
        if condition not in seen_conditions:
            await db.delete(rule)

    kept: list[AlertRule] = []
    for row in payload.rows:
        rule = existing_by_condition.get(row.condition)
        if rule is None:
            rule = AlertRule(
                owner_id=current_user.id,
                monitor_id=monitor_id,
                condition=row.condition,
            )
            db.add(rule)
        for field in _MATRIX_RULE_FIELDS:
            setattr(rule, field, getattr(row, field))
        rule.channels = [channels_by_id[cid] for cid in row.channel_ids]
        kept.append(rule)

    await db.flush()
    return AlertMatrixOut(monitor_id=monitor_id, rows=kept)


# ── Threshold suggestions ────────────────────────────────────────────────


@router.get("/suggestions/thresholds")
@limiter.limit("10/minute")
async def get_threshold_suggestions(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Return monitors that could benefit from a response_time_above alert rule,
    with a suggested threshold based on their p95 over the last 7 days."""
    return await compute_threshold_suggestions(db, owner_id=current_user.id)
