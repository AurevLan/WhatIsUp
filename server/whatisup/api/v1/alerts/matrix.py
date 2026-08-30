"""Alert matrix (conditions × channels per monitor) + matrix templates."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from whatisup.api.deps import check_resource_access, get_current_user, require_superadmin
from whatisup.api.v1.alerts._common import _fetch_channels_by_ids
from whatisup.core.database import get_db
from whatisup.core.limiter import limiter
from whatisup.models.alert import METRIC_CONDITIONS, AlertChannel, AlertCondition, AlertRule
from whatisup.models.alert_matrix_template import AlertMatrixTemplate
from whatisup.models.monitor import Monitor
from whatisup.models.team import TeamRole
from whatisup.models.user import User
from whatisup.schemas.alert import AlertMatrixIn, AlertMatrixOut
from whatisup.schemas.alert_matrix_template import (
    AlertMatrixTemplateIn,
    AlertMatrixTemplateOut,
    AlertMatrixTemplateUpdate,
)

router = APIRouter(prefix="/alerts", tags=["alerts"])


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
@limiter.limit("60/minute")
async def list_matrix_templates(
    request: Request,
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
@limiter.limit("60/minute")
async def get_alert_matrix(
    request: Request,
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

    Pushed-metric conditions (C-4) are deliberately out of the matrix: its whole
    data model is one rule per condition, while a monitor legitimately has
    several ``metric_above`` rules watching different metrics. They are rejected
    on input *and* held out of the delete sweep below — a matrix save must not
    wipe rules it was never able to display.
    """
    monitor = await _load_monitor_with_rules(monitor_id, current_user, db, min_role=TeamRole.editor)

    seen_conditions: set[AlertCondition] = set()
    for row in payload.rows:
        if row.condition in METRIC_CONDITIONS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Condition {row.condition} is managed per metric, not by the matrix — "
                    "use POST /alerts/rules"
                ),
            )
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
        r.condition: r for r in monitor.alert_rules if r.condition not in METRIC_CONDITIONS
    }

    deleted_conditions = [c for c in existing_by_condition if c not in seen_conditions]
    for condition in deleted_conditions:
        await db.delete(existing_by_condition[condition])

    created_conditions: list[AlertCondition] = []
    updated_conditions: list[AlertCondition] = []
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
            created_conditions.append(row.condition)
        else:
            updated_conditions.append(row.condition)
        for field in _MATRIX_RULE_FIELDS:
            setattr(rule, field, getattr(row, field))
        rule.channels = [channels_by_id[cid] for cid in row.channel_ids]
        kept.append(rule)

    await db.flush()

    from whatisup.services.audit import log_action

    # Bulk endpoint (create + update + delete AlertRules in one shot) — a single
    # synthetic trace per request is enough, matching the resource actually being
    # edited (the monitor's alert matrix) rather than one entry per underlying rule.
    await log_action(
        db,
        "alert_rule.matrix_update",
        "monitor",
        monitor_id,
        monitor.name,
        current_user,
        diff={
            "created": len(created_conditions),
            "updated": len(updated_conditions),
            "deleted": len(deleted_conditions),
            "created_conditions": [str(c) for c in created_conditions],
            "updated_conditions": [str(c) for c in updated_conditions],
            "deleted_conditions": [str(c) for c in deleted_conditions],
        },
    )

    return AlertMatrixOut(monitor_id=monitor_id, rows=kept)
