"""Alert rule endpoints — CRUD, simulate, events, presets, auto-rules."""

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
)
from whatisup.api.v1.alerts._common import _fetch_channels_by_ids
from whatisup.core.database import get_db
from whatisup.core.limiter import limiter
from whatisup.models.alert import AlertChannel, AlertEvent, AlertRule
from whatisup.models.incident import Incident
from whatisup.models.monitor import Monitor, MonitorGroup
from whatisup.models.team import TeamRole
from whatisup.models.user import User
from whatisup.schemas.alert import (
    AlertEventOut,
    AlertRuleCreate,
    AlertRuleOut,
    AlertRuleSimulateOut,
    AlertRuleUpdate,
    assert_metric_rule_is_fireable,
)
from whatisup.services.alert import simulate_rule
from whatisup.services.alert_presets import get_presets

router = APIRouter(prefix="/alerts", tags=["alerts"])


# ── Rules ─────────────────────────────────────────────────────────────────


@router.get("/rules", response_model=list[AlertRuleOut])
@limiter.limit("60/minute")
async def list_rules(
    request: Request,
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
@limiter.limit("30/minute")
async def create_rule(
    request: Request,
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
    await _assert_can_use_escalation_policy(db, current_user, payload.escalation_policy_id)

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
        # anomaly_zscore_threshold and schedule were declared on AlertRuleCreate
        # but never assigned here: the single-rule endpoints silently dropped
        # them and only the matrix endpoint honoured them.
        anomaly_zscore_threshold=payload.anomaly_zscore_threshold,
        metric_name=payload.metric_name,
        metric_labels=payload.metric_labels,
        metric_window_seconds=payload.metric_window_seconds,
        schedule=payload.schedule,
        suppress_on_network_partition=payload.suppress_on_network_partition,
        escalation_policy_id=payload.escalation_policy_id,
        channels=channels,
    )
    db.add(rule)
    await db.flush()
    await db.refresh(rule, ["channels"])
    from whatisup.services.audit import log_action

    await log_action(
        db,
        "alert_rule.create",
        "alert_rule",
        rule.id,
        str(rule.condition),
        current_user,
        diff={"monitor_id": str(rule.monitor_id) if rule.monitor_id else None},
    )
    return rule


async def _assert_can_use_escalation_policy(
    db: AsyncSession, user: User, policy_id: uuid.UUID | None
) -> None:
    """Reject attaching a rule to an escalation policy the caller cannot access.

    Unchecked, this would let any account borrow another tenant's ladder — and
    through it, their alert channels and on-call roster.
    """
    if policy_id is None:
        return
    from whatisup.models.oncall import EscalationPolicy

    policy = (
        await db.execute(select(EscalationPolicy).where(EscalationPolicy.id == policy_id))
    ).scalar_one_or_none()
    if policy is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Escalation policy not found"
        )
    await check_resource_access(policy, user, db)


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
    if payload.anomaly_zscore_threshold is not None:
        rule.anomaly_zscore_threshold = payload.anomaly_zscore_threshold
    if payload.metric_name is not None:
        rule.metric_name = payload.metric_name
    if payload.metric_labels is not None:
        rule.metric_labels = payload.metric_labels or None
    if payload.metric_window_seconds is not None:
        rule.metric_window_seconds = payload.metric_window_seconds
    if payload.schedule is not None:
        rule.schedule = payload.schedule
    if payload.suppress_on_network_partition is not None:
        rule.suppress_on_network_partition = payload.suppress_on_network_partition
    # `exclude_unset` rather than a None test: None is a meaningful value here —
    # it detaches the ladder and returns the rule to the channel fan-out.
    if "escalation_policy_id" in payload.model_fields_set:
        await _assert_can_use_escalation_policy(db, current_user, payload.escalation_policy_id)
        rule.escalation_policy_id = payload.escalation_policy_id

    if payload.channel_ids is not None:
        rule.channels = await _fetch_channels_by_ids(db, current_user, payload.channel_ids)

    # Validated on the *merged* state, not on the payload: switching an existing
    # rule to a metric condition without also sending metric_name would sail
    # through a payload-only check and store a rule that can never fire.
    try:
        assert_metric_rule_is_fireable(
            rule.condition, rule.metric_name, rule.threshold_value, rule.monitor_id
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    await db.flush()
    await db.refresh(rule, ["channels"])
    from whatisup.services.audit import log_action

    await log_action(
        db,
        "alert_rule.update",
        "alert_rule",
        rule.id,
        str(rule.condition),
        current_user,
        diff={"monitor_id": str(rule.monitor_id) if rule.monitor_id else None},
    )
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
    from whatisup.services.audit import log_action

    await log_action(
        db,
        "alert_rule.delete",
        "alert_rule",
        rule.id,
        str(rule.condition),
        current_user,
        diff={"monitor_id": str(rule.monitor_id) if rule.monitor_id else None},
    )
    await db.delete(rule)


# ── Events ────────────────────────────────────────────────────────────────


@router.get("/events", response_model=list[AlertEventOut])
@limiter.limit("60/minute")
async def list_events(
    request: Request,
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
@limiter.limit("60/minute")
async def get_alert_presets(
    request: Request,
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

    from whatisup.services.audit import log_action

    await log_action(
        db,
        "alert_rule.auto_create",
        "monitor",
        monitor_id,
        monitor.name,
        current_user,
        diff={
            "created": len(created),
            "conditions": [str(r.condition) for r in created],
        },
    )

    return created
