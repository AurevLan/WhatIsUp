"""Monitor CRUD endpoints."""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import and_, case, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.api.deps import get_current_user, require_superadmin
from whatisup.core.database import get_db
from whatisup.core.limiter import limiter
from whatisup.core.security import encrypt_scenario_variables
from whatisup.models.annotation import MonitorAnnotation
from whatisup.models.monitor import CompositeMonitorMember, Monitor
from whatisup.models.probe import Probe
from whatisup.models.result import CheckResult, CheckStatus
from whatisup.models.tag import Tag
from whatisup.models.user import User
from whatisup.schemas.annotation import AnnotationCreate, AnnotationOut
from whatisup.schemas.incident import IncidentOut
from whatisup.schemas.monitor import (
    BulkActionRequest,
    BulkActionResponse,
    CompositeMonitorMemberCreate,
    CompositeMonitorMemberOut,
    MonitorCreate,
    MonitorDependencyCreate,
    MonitorDependencyOut,
    MonitorOut,
    MonitorUpdate,
)
from whatisup.schemas.probe import ProbeMonitorStatus
from whatisup.schemas.result import CheckResultOut, UptimeStats
from whatisup.services.stats import compute_uptime

router = APIRouter(prefix="/monitors", tags=["monitors"])


async def _get_monitor_or_404(monitor_id: uuid.UUID, user: User, db: AsyncSession) -> Monitor:
    monitor = (
        await db.execute(select(Monitor).where(Monitor.id == monitor_id))
    ).scalar_one_or_none()
    if monitor is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Monitor not found")
    # Superadmin sees all; others see only their own
    if not user.is_superadmin and monitor.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    return monitor


@router.get("/", response_model=list[MonitorOut])
async def list_monitors(
    enabled: bool | None = None,
    group_id: uuid.UUID | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    query = select(Monitor)
    if not current_user.is_superadmin:
        query = query.where(Monitor.owner_id == current_user.id)
    if enabled is not None:
        query = query.where(Monitor.enabled == enabled)
    if group_id is not None:
        query = query.where(Monitor.group_id == group_id)
    monitors = list((await db.execute(query.order_by(Monitor.created_at.desc()))).scalars().all())

    if not monitors:
        return []

    monitor_ids = [m.id for m in monitors]

    # Latest status per monitor (one query — join on max checked_at)
    max_ts_subq = (
        select(
            CheckResult.monitor_id,
            func.max(CheckResult.checked_at).label("max_at"),
        )
        .where(CheckResult.monitor_id.in_(monitor_ids))
        .group_by(CheckResult.monitor_id)
        .subquery()
    )
    latest_rows = (
        await db.execute(
            select(CheckResult.monitor_id, CheckResult.status, CheckResult.checked_at).join(
                max_ts_subq,
                and_(
                    CheckResult.monitor_id == max_ts_subq.c.monitor_id,
                    CheckResult.checked_at == max_ts_subq.c.max_at,
                ),
            )
        )
    ).all()
    # Map: monitor_id → (status_value, checked_at)
    latest_map = {str(r.monitor_id): (r.status.value, r.checked_at) for r in latest_rows}

    # Uptime 24h per monitor (one query)
    cutoff = datetime.now(UTC) - timedelta(hours=24)
    uptime_rows = (
        await db.execute(
            select(
                CheckResult.monitor_id,
                func.count(CheckResult.id).label("total"),
                func.sum(case((CheckResult.status == CheckStatus.up, 1), else_=0)).label(
                    "up_count"
                ),
            )
            .where(
                CheckResult.monitor_id.in_(monitor_ids),
                CheckResult.checked_at >= cutoff,
            )
            .group_by(CheckResult.monitor_id)
        )
    ).all()
    uptime_map = {
        str(r.monitor_id): round(r.up_count / r.total * 100, 2) for r in uptime_rows if r.total > 0
    }

    now = datetime.now(UTC)
    out = []
    for m in monitors:
        mid = str(m.id)
        d = MonitorOut.model_validate(m).model_dump()
        entry = latest_map.get(mid)
        if entry:
            status_val, checked_at = entry
            age = (now - checked_at).total_seconds()
            threshold = max(300, m.interval_seconds * 3)
            d["last_status"] = status_val if age < threshold else None
        else:
            d["last_status"] = None
        d["uptime_24h"] = uptime_map.get(mid)
        out.append(d)
    return out


@router.post("/", response_model=MonitorOut, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
async def create_monitor(
    request: Request,
    payload: MonitorCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Monitor:
    tags = []
    if payload.tag_ids:
        tags_result = await db.execute(select(Tag).where(Tag.id.in_(payload.tag_ids)))
        tags = list(tags_result.scalars().all())
        if len(tags) != len(payload.tag_ids):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Some tags not found"
            )

    monitor = Monitor(
        name=payload.name,
        url=str(payload.url),
        group_id=payload.group_id,
        owner_id=current_user.id,
        interval_seconds=payload.interval_seconds,
        timeout_seconds=payload.timeout_seconds,
        follow_redirects=payload.follow_redirects,
        expected_status_codes=payload.expected_status_codes,
        enabled=payload.enabled,
        ssl_check_enabled=payload.ssl_check_enabled,
        ssl_expiry_warn_days=payload.ssl_expiry_warn_days,
        tags=tags,
        check_type=payload.check_type,
        tcp_port=payload.tcp_port,
        udp_port=payload.udp_port,
        smtp_port=payload.smtp_port,
        smtp_starttls=payload.smtp_starttls,
        domain_expiry_warn_days=payload.domain_expiry_warn_days,
        dns_record_type=payload.dns_record_type,
        dns_expected_value=payload.dns_expected_value,
        keyword=payload.keyword,
        keyword_negate=payload.keyword_negate,
        expected_json_path=payload.expected_json_path,
        expected_json_value=payload.expected_json_value,
        scenario_steps=(
            [s.model_dump() for s in payload.scenario_steps]
            if payload.scenario_steps
            else None
        ),
        scenario_variables=encrypt_scenario_variables(
            [v.model_dump() for v in payload.scenario_variables]
        ) if payload.scenario_variables else None,
        heartbeat_slug=payload.heartbeat_slug,
        heartbeat_interval_seconds=payload.heartbeat_interval_seconds,
        heartbeat_grace_seconds=payload.heartbeat_grace_seconds,
        body_regex=payload.body_regex,
        expected_headers=payload.expected_headers,
        json_schema=payload.json_schema,
        slo_target=payload.slo_target,
        slo_window_days=payload.slo_window_days,
        dns_drift_alert=payload.dns_drift_alert,
        dns_consistency_check=payload.dns_consistency_check,
        dns_allow_split_horizon=payload.dns_allow_split_horizon,
        composite_aggregation=payload.composite_aggregation,
    )
    db.add(monitor)
    await db.flush()

    from whatisup.services.audit import log_action

    await log_action(db, "monitor.create", "monitor", monitor.id, monitor.name, current_user)

    return monitor


@router.post("/bulk", response_model=BulkActionResponse)
@limiter.limit("20/minute")
async def bulk_action(
    request: Request,
    payload: BulkActionRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Bulk enable / pause / delete monitors owned by the current user."""
    # Ownership filter — superadmin can act on all; others only on their own
    ownership_clause = (
        Monitor.id.in_(payload.ids)
        if current_user.is_superadmin
        else and_(Monitor.id.in_(payload.ids), Monitor.owner_id == current_user.id)
    )

    if payload.action == "delete":
        result = await db.execute(delete(Monitor).where(ownership_clause))
        affected = result.rowcount
    elif payload.action == "enable":
        result = await db.execute(update(Monitor).where(ownership_clause).values(enabled=True))
        affected = result.rowcount
    else:  # pause
        result = await db.execute(update(Monitor).where(ownership_clause).values(enabled=False))
        affected = result.rowcount

    return {"affected": affected}


@router.get("/{monitor_id}", response_model=MonitorOut)
async def get_monitor(
    monitor_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Monitor:
    return await _get_monitor_or_404(monitor_id, current_user, db)


@router.patch("/{monitor_id}", response_model=MonitorOut)
async def update_monitor(
    monitor_id: uuid.UUID,
    payload: MonitorUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Monitor:
    monitor = await _get_monitor_or_404(monitor_id, current_user, db)

    before = MonitorOut.model_validate(monitor).model_dump(mode="json")

    update_data = payload.model_dump(exclude_unset=True)
    tag_ids = update_data.pop("tag_ids", None)

    for field, value in update_data.items():
        if field == "url" and value is not None:
            value = str(value)
        elif field == "scenario_variables" and value is not None:
            # Encrypt secret variables before persisting; skip empty-value entries
            # (empty value means "unchanged" when the UI re-submits masked data)
            non_empty = [v for v in value if not (v.get("secret") and not v.get("value"))]
            value = encrypt_scenario_variables(non_empty)
        setattr(monitor, field, value)

    if tag_ids is not None:
        tags_result = await db.execute(select(Tag).where(Tag.id.in_(tag_ids)))
        monitor.tags = list(tags_result.scalars().all())

    await db.flush()

    after = MonitorOut.model_validate(monitor).model_dump(mode="json")
    from whatisup.services.audit import log_action

    await log_action(
        db,
        "monitor.update",
        "monitor",
        monitor.id,
        monitor.name,
        current_user,
        diff={"before": before, "after": after},
    )

    return monitor


@router.delete("/{monitor_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_monitor(
    monitor_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    monitor = await _get_monitor_or_404(monitor_id, current_user, db)
    from whatisup.services.audit import log_action

    await log_action(db, "monitor.delete", "monitor", monitor.id, monitor.name, current_user)
    await db.delete(monitor)


@router.get("/{monitor_id}/results", response_model=list[CheckResultOut])
async def get_results(
    monitor_id: uuid.UUID,
    limit: int = Query(default=100, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
    since: datetime | None = Query(
        default=None, description="ISO datetime — only results after this timestamp"
    ),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list:
    await _get_monitor_or_404(monitor_id, current_user, db)
    query = select(CheckResult).where(CheckResult.monitor_id == monitor_id)
    if since is not None:
        query = query.where(CheckResult.checked_at >= since)
    query = query.order_by(CheckResult.checked_at.desc()).limit(limit).offset(offset)
    result = await db.execute(query)
    return list(result.scalars().all())


@router.get("/{monitor_id}/uptime", response_model=UptimeStats)
async def get_uptime(
    monitor_id: uuid.UUID,
    period_hours: int = Query(default=24, ge=1, le=2160),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UptimeStats:
    await _get_monitor_or_404(monitor_id, current_user, db)
    return await compute_uptime(db, monitor_id, period_hours)


@router.get("/{monitor_id}/history", response_model=list[dict])
async def get_history(
    monitor_id: uuid.UUID,
    days: int = Query(default=90, ge=1, le=365),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Daily uptime history for the last N days (for history bars UI)."""
    await _get_monitor_or_404(monitor_id, current_user, db)
    from whatisup.services.stats import compute_daily_history

    return await compute_daily_history(db, monitor_id, days)


@router.get("/{monitor_id}/probes", response_model=list[ProbeMonitorStatus])
async def get_monitor_probe_status(
    monitor_id: uuid.UUID,
    _user: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Last check result per probe for a given monitor."""
    # Subquery: MAX(checked_at) per probe_id for this monitor
    max_ts_subq = (
        select(
            CheckResult.probe_id,
            func.max(CheckResult.checked_at).label("max_at"),
        )
        .where(CheckResult.monitor_id == monitor_id)
        .group_by(CheckResult.probe_id)
        .subquery()
    )

    # Latest result row per probe
    latest_rows = (
        await db.execute(
            select(
                CheckResult.probe_id,
                CheckResult.status,
                CheckResult.checked_at,
                CheckResult.response_time_ms,
            ).join(
                max_ts_subq,
                and_(
                    CheckResult.probe_id == max_ts_subq.c.probe_id,
                    CheckResult.checked_at == max_ts_subq.c.max_at,
                    CheckResult.monitor_id == monitor_id,
                ),
            )
        )
    ).all()
    latest_map = {str(r.probe_id): r for r in latest_rows}

    # All probes
    probes = list((await db.execute(select(Probe).order_by(Probe.name))).scalars().all())

    out = []
    for p in probes:
        row = latest_map.get(str(p.id))
        out.append(
            ProbeMonitorStatus(
                probe_id=p.id,
                name=p.name,
                location_name=p.location_name,
                latitude=p.latitude,
                longitude=p.longitude,
                is_active=p.is_active,
                last_seen_at=p.last_seen_at,
                last_status=row.status if row else None,
                last_checked_at=row.checked_at if row else None,
                response_time_ms=row.response_time_ms if row else None,
            )
        )
    return out


@router.post("/{monitor_id}/trigger-check", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit("10/minute")
async def trigger_check(
    request: Request,
    monitor_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Request an immediate check of this monitor on the next probe heartbeat cycle."""
    await _get_monitor_or_404(monitor_id, current_user, db)
    from whatisup.core.redis import get_redis

    redis = get_redis()
    await redis.setex(f"whatisup:trigger_check:{monitor_id}", 120, "1")
    return {"status": "queued", "monitor_id": str(monitor_id)}


@router.get("/{monitor_id}/incidents", response_model=list[IncidentOut])
async def get_incidents(
    monitor_id: uuid.UUID,
    resolved: bool | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list:
    from whatisup.models.incident import Incident

    await _get_monitor_or_404(monitor_id, current_user, db)
    query = select(Incident).where(Incident.monitor_id == monitor_id)
    if resolved is True:
        query = query.where(Incident.resolved_at.isnot(None))
    elif resolved is False:
        query = query.where(Incident.resolved_at.is_(None))
    query = query.order_by(Incident.started_at.desc()).limit(limit)
    result = await db.execute(query)
    return list(result.scalars().all())


@router.get("/{monitor_id}/incidents/{incident_id}/postmortem")
async def get_postmortem(
    monitor_id: uuid.UUID,
    incident_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Génère un post-mortem markdown structuré pour un incident résolu."""
    from whatisup.models.alert import AlertChannel, AlertEvent
    from whatisup.models.incident import Incident

    monitor = await _get_monitor_or_404(monitor_id, current_user, db)

    # Ownership check via monitor (déjà fait par _get_monitor_or_404)
    incident = (
        await db.execute(
            select(Incident).where(
                Incident.id == incident_id,
                Incident.monitor_id == monitor_id,
            )
        )
    ).scalar_one_or_none()
    if incident is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incident introuvable")

    now_utc = datetime.now(UTC)
    window_start = incident.started_at - timedelta(minutes=5)
    window_end = (incident.resolved_at or now_utc) + timedelta(minutes=5)

    # Checks pendant la fenêtre
    check_rows = (
        (
            await db.execute(
                select(CheckResult)
                .where(
                    CheckResult.monitor_id == monitor_id,
                    CheckResult.checked_at >= window_start,
                    CheckResult.checked_at <= window_end,
                )
                .order_by(CheckResult.checked_at.asc())
            )
        )
        .scalars()
        .all()
    )

    total_checks = len(check_rows)
    failed_checks = sum(1 for r in check_rows if r.status.value not in ("up",))
    failure_pct = round(failed_checks / total_checks * 100, 1) if total_checks > 0 else 0
    avg_rt_values = [r.response_time_ms for r in check_rows if r.response_time_ms is not None]
    avg_rt = round(sum(avg_rt_values) / len(avg_rt_values)) if avg_rt_values else None

    # AlertEvents liés à l'incident (avec nom du canal)
    alert_events_rows = (
        await db.execute(
            select(AlertEvent, AlertChannel.name)
            .join(AlertChannel, AlertEvent.channel_id == AlertChannel.id)
            .where(AlertEvent.incident_id == incident_id)
            .order_by(AlertEvent.sent_at.asc())
        )
    ).all()

    # Annotations dans la fenêtre
    annotations_rows = (
        (
            await db.execute(
                select(MonitorAnnotation)
                .where(
                    MonitorAnnotation.monitor_id == monitor_id,
                    MonitorAnnotation.annotated_at >= window_start,
                    MonitorAnnotation.annotated_at <= window_end,
                )
                .order_by(MonitorAnnotation.annotated_at.asc())
            )
        )
        .scalars()
        .all()
    )

    # Calcul durée
    if incident.resolved_at:
        dur_secs = int((incident.resolved_at - incident.started_at).total_seconds())
        dur_label = f"{dur_secs // 60} min {dur_secs % 60} s"
        downtime_minutes = round(dur_secs / 60, 1)
        resolved_str = incident.resolved_at.strftime("%Y-%m-%d %H:%M UTC")
    else:
        dur_label = "en cours"
        downtime_minutes = round((now_utc - incident.started_at).total_seconds() / 60, 1)
        resolved_str = "_en cours_"

    started_str = incident.started_at.strftime("%Y-%m-%d %H:%M UTC")

    # Construction de la chronologie
    timeline_rows = [
        f"| {incident.started_at.strftime('%H:%M UTC')}"
        f" | ❌ Incident ouvert — {incident.scope.value} |"
    ]
    for evt, ch_name in alert_events_rows:
        icon = "📧" if evt.status.value == "sent" else "⚠️"
        timeline_rows.append(
            f"| {evt.sent_at.strftime('%H:%M UTC')} | {icon} Alerte envoyée via {ch_name} |"
        )
    if incident.resolved_at:
        timeline_rows.append(
            f"| {incident.resolved_at.strftime('%H:%M UTC')} | ✅ Incident résolu |"
        )
    timeline_md = "\n".join(timeline_rows)

    # Annotations markdown
    if annotations_rows:
        ann_lines = "\n".join(
            f"- **{a.annotated_at.strftime('%H:%M UTC')}** — {a.content}"
            + (f" _(par {a.created_by})_" if a.created_by else "")
            for a in annotations_rows
        )
    else:
        ann_lines = "_Aucune annotation dans cette période._"

    markdown = f"""# Post-mortem : {monitor.name}

**Durée** : {started_str} → {resolved_str} ({dur_label})
**Impact** : {downtime_minutes} minutes d'indisponibilité

## Chronologie
| Heure | Événement |
|-------|-----------|
{timeline_md}

## Métriques pendant l'incident
- Checks effectués : {total_checks}
- Taux d'échec : {failure_pct}%
- Temps de réponse moyen : {avg_rt if avg_rt is not None else "—"}ms

## Actions correctives
<!-- À compléter -->

## Annotations
{ann_lines}
"""

    return {
        "content": markdown.strip(),
        "generated_at": now_utc.isoformat(),
    }


@router.get("/{monitor_id}/report")
@limiter.limit("20/minute")
async def get_sla_report(
    request: Request,
    monitor_id: uuid.UUID,
    from_: datetime = Query(alias="from", description="ISO datetime start"),
    to: datetime = Query(default=None, description="ISO datetime end (default: now)"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """SLA report for a custom date range."""
    await _get_monitor_or_404(monitor_id, current_user, db)
    if to is None:
        to = datetime.now(UTC)

    result = await db.execute(
        select(
            func.count(CheckResult.id).label("total"),
            func.sum(case((CheckResult.status == CheckStatus.up, 1), else_=0)).label("up_count"),
            func.avg(CheckResult.response_time_ms).label("avg_rt"),
            func.percentile_cont(0.95).within_group(CheckResult.response_time_ms).label("p95_rt"),
            func.min(CheckResult.response_time_ms).label("min_rt"),
            func.max(CheckResult.response_time_ms).label("max_rt"),
        ).where(
            CheckResult.monitor_id == monitor_id,
            CheckResult.checked_at >= from_,
            CheckResult.checked_at <= to,
        )
    )
    row = result.one()
    total = int(row.total or 0)
    up_count = int(row.up_count or 0)

    # Count incidents in period
    from whatisup.models.incident import Incident

    inc_result = await db.execute(
        select(
            func.count(Incident.id).label("count"),
            func.sum(Incident.duration_seconds).label("total_downtime"),
        ).where(
            Incident.monitor_id == monitor_id,
            Incident.started_at >= from_,
            Incident.started_at <= to,
        )
    )
    inc_row = inc_result.one()

    return {
        "monitor_id": str(monitor_id),
        "from": from_.isoformat(),
        "to": to.isoformat(),
        "total_checks": total,
        "up_checks": up_count,
        "uptime_percent": round(up_count / total * 100, 4) if total > 0 else 100.0,
        "avg_response_time_ms": float(row.avg_rt) if row.avg_rt else None,
        "p95_response_time_ms": float(row.p95_rt) if row.p95_rt else None,
        "min_response_time_ms": float(row.min_rt) if row.min_rt else None,
        "max_response_time_ms": float(row.max_rt) if row.max_rt else None,
        "incident_count": int(inc_row.count or 0),
        "total_downtime_seconds": int(inc_row.total_downtime or 0),
    }


@router.get("/{monitor_id}/annotations")
async def list_annotations(
    monitor_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    await _get_monitor_or_404(monitor_id, current_user, db)
    rows = (
        (
            await db.execute(
                select(MonitorAnnotation)
                .where(MonitorAnnotation.monitor_id == monitor_id)
                .order_by(MonitorAnnotation.annotated_at.desc())
                .limit(200)
            )
        )
        .scalars()
        .all()
    )
    return [AnnotationOut.model_validate(r).model_dump(mode="json") for r in rows]


@router.post("/{monitor_id}/annotations", status_code=status.HTTP_201_CREATED)
async def create_annotation(
    monitor_id: uuid.UUID,
    payload: AnnotationCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await _get_monitor_or_404(monitor_id, current_user, db)
    ann = MonitorAnnotation(
        monitor_id=monitor_id,
        content=payload.content,
        annotated_at=payload.annotated_at,
        created_at=datetime.now(UTC),
        created_by=current_user.username,
    )
    db.add(ann)
    await db.flush()
    return AnnotationOut.model_validate(ann).model_dump(mode="json")


@router.delete("/{monitor_id}/annotations/{annotation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_annotation(
    monitor_id: uuid.UUID,
    annotation_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await _get_monitor_or_404(monitor_id, current_user, db)
    ann = (
        await db.execute(
            select(MonitorAnnotation).where(
                MonitorAnnotation.id == annotation_id,
                MonitorAnnotation.monitor_id == monitor_id,
            )
        )
    ).scalar_one_or_none()
    if ann is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Annotation not found")
    await db.delete(ann)


@router.get("/{monitor_id}/slo")
@limiter.limit("30/minute")
async def get_slo(
    request: Request,
    monitor_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """SLO / Error Budget status for a monitor."""
    from whatisup.models.incident import Incident

    monitor = await _get_monitor_or_404(monitor_id, current_user, db)

    if monitor.slo_target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="SLO non configuré sur ce moniteur",
        )

    window_days = monitor.slo_window_days or 30
    slo_target = monitor.slo_target
    now = datetime.now(UTC)
    window_start = now - timedelta(days=window_days)

    # Uptime over the SLO window
    uptime_row = (
        await db.execute(
            select(
                func.count(CheckResult.id).label("total"),
                func.sum(case((CheckResult.status == CheckStatus.up, 1), else_=0)).label(
                    "up_count"
                ),
            ).where(
                CheckResult.monitor_id == monitor_id,
                CheckResult.checked_at >= window_start,
            )
        )
    ).one()

    total_checks = int(uptime_row.total or 0)
    up_count = int(uptime_row.up_count or 0)
    uptime_pct = round(up_count / total_checks * 100, 4) if total_checks > 0 else 100.0

    # Downtime from resolved incidents in the window
    inc_row = (
        await db.execute(
            select(
                func.coalesce(func.sum(Incident.duration_seconds), 0).label("total_downtime_s"),
            ).where(
                Incident.monitor_id == monitor_id,
                Incident.started_at >= window_start,
                Incident.resolved_at.isnot(None),
            )
        )
    ).one()
    downtime_minutes = float(inc_row.total_downtime_s or 0) / 60.0

    # Error budget calculation
    error_budget_total_minutes = window_days * 24 * 60 * (1 - slo_target / 100)
    error_budget_remaining_minutes = error_budget_total_minutes - downtime_minutes
    error_budget_used_minutes = downtime_minutes
    burn_rate = (
        downtime_minutes / error_budget_total_minutes if error_budget_total_minutes > 0 else 0.0
    )

    if burn_rate >= 1.0:
        slo_status = "exhausted"
    elif burn_rate > 0.8:
        slo_status = "critical"
    elif burn_rate > 0.5:
        slo_status = "at_risk"
    else:
        slo_status = "healthy"

    return {
        "slo_target": slo_target,
        "window_days": window_days,
        "uptime_pct": uptime_pct,
        "error_budget_total_minutes": round(error_budget_total_minutes, 2),
        "error_budget_used_minutes": round(error_budget_used_minutes, 2),
        "error_budget_remaining_minutes": round(error_budget_remaining_minutes, 2),
        "burn_rate": round(burn_rate, 4),
        "status": slo_status,
    }


# ---------------------------------------------------------------------------
# Monitor dependencies
# ---------------------------------------------------------------------------


@router.get(
    "/{monitor_id}/dependencies",
    response_model=list[MonitorDependencyOut],
)
@limiter.limit("60/minute")
async def list_dependencies(
    request: Request,
    monitor_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list:
    """List all parent monitors this monitor depends on."""
    from whatisup.models.monitor import MonitorDependency

    await _get_monitor_or_404(monitor_id, current_user, db)
    rows = (
        await db.execute(
            select(MonitorDependency).where(MonitorDependency.child_id == monitor_id)
        )
    ).scalars().all()
    return list(rows)


@router.post(
    "/{monitor_id}/dependencies",
    response_model=MonitorDependencyOut,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("30/minute")
async def add_dependency(
    request: Request,
    monitor_id: uuid.UUID,
    payload: MonitorDependencyCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> object:
    """Declare that this monitor depends on a parent monitor.

    When the parent has an open incident and ``suppress_on_parent_down`` is
    ``true``, incidents on this (child) monitor will be suppressed.
    """
    from whatisup.models.monitor import MonitorDependency

    child = await _get_monitor_or_404(monitor_id, current_user, db)
    parent = await _get_monitor_or_404(payload.parent_id, current_user, db)

    if parent.id == child.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A monitor cannot depend on itself",
        )

    # Check for duplicates
    existing = (
        await db.execute(
            select(MonitorDependency).where(
                MonitorDependency.parent_id == parent.id,
                MonitorDependency.child_id == child.id,
            )
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Dependency already exists",
        )

    dep = MonitorDependency(
        parent_id=parent.id,
        child_id=child.id,
        suppress_on_parent_down=payload.suppress_on_parent_down,
    )
    db.add(dep)
    await db.flush()
    return dep


@router.delete(
    "/{monitor_id}/dependencies/{dependency_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_dependency(
    monitor_id: uuid.UUID,
    dependency_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Remove a parent dependency from this monitor."""
    from whatisup.models.monitor import MonitorDependency

    await _get_monitor_or_404(monitor_id, current_user, db)
    dep = (
        await db.execute(
            select(MonitorDependency).where(
                MonitorDependency.id == dependency_id,
                MonitorDependency.child_id == monitor_id,
            )
        )
    ).scalar_one_or_none()
    if dep is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Dependency not found"
        )
    await db.delete(dep)


# ---------------------------------------------------------------------------
# DNS baseline management
# ---------------------------------------------------------------------------


@router.post("/{monitor_id}/dns-baseline/accept", status_code=status.HTTP_200_OK)
@limiter.limit("20/minute")
async def accept_dns_baseline(
    request: Request,
    monitor_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Accept the current DNS resolved values as the new baseline.

    Fetches the most recent successful DNS check result for this monitor
    and stores its resolved IPs as the new drift-detection baseline.
    Clears any existing open incident caused by a drift.
    """
    monitor = await _get_monitor_or_404(monitor_id, current_user, db)
    if monitor.check_type != "dns":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="DNS baseline only applies to dns check_type monitors",
        )

    latest = (
        await db.execute(
            select(CheckResult)
            .where(
                CheckResult.monitor_id == monitor_id,
                CheckResult.dns_resolved_values.isnot(None),
            )
            .order_by(CheckResult.checked_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    if latest is None or not latest.dns_resolved_values:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No DNS result available yet — wait for the first check",
        )

    new_baseline = sorted(latest.dns_resolved_values)
    monitor.dns_baseline_ips = new_baseline
    await db.flush()

    return {"baseline": new_baseline, "accepted_at": latest.checked_at.isoformat()}


@router.delete("/{monitor_id}/dns-baseline", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("20/minute")
async def reset_dns_baseline(
    request: Request,
    monitor_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Clear the DNS baseline — the next successful check will re-learn it."""
    monitor = await _get_monitor_or_404(monitor_id, current_user, db)
    if monitor.check_type != "dns":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="DNS baseline only applies to dns check_type monitors",
        )
    monitor.dns_baseline_ips = None


# ---------------------------------------------------------------------------
# Schema drift baseline management
# ---------------------------------------------------------------------------


@router.post("/{monitor_id}/schema-baseline/accept", status_code=status.HTTP_200_OK)
@limiter.limit("20/minute")
async def accept_schema_baseline(
    request: Request,
    monitor_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Accept the current API schema fingerprint as the new baseline for drift detection."""
    from datetime import UTC, datetime

    monitor = await _get_monitor_or_404(monitor_id, current_user, db)

    latest = (
        await db.execute(
            select(CheckResult)
            .where(
                CheckResult.monitor_id == monitor_id,
                CheckResult.schema_fingerprint.isnot(None),
            )
            .order_by(CheckResult.checked_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    if latest is None or not latest.schema_fingerprint:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No schema fingerprint available yet — enable schema_drift_enabled and wait for a check",
        )

    monitor.schema_baseline = latest.schema_fingerprint
    monitor.schema_baseline_updated_at = datetime.now(UTC)
    await db.commit()

    return {
        "baseline": monitor.schema_baseline,
        "accepted_at": latest.checked_at.isoformat(),
    }


@router.delete("/{monitor_id}/schema-baseline", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("20/minute")
async def reset_schema_baseline(
    request: Request,
    monitor_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Clear the schema baseline — the next successful check will set a new one."""
    monitor = await _get_monitor_or_404(monitor_id, current_user, db)
    monitor.schema_baseline = None
    monitor.schema_baseline_updated_at = None
    await db.commit()


# ---------------------------------------------------------------------------
# Composite monitor members
# ---------------------------------------------------------------------------


@router.get(
    "/{monitor_id}/composite-members",
    response_model=list[CompositeMonitorMemberOut],
)
@limiter.limit("60/minute")
async def list_composite_members(
    request: Request,
    monitor_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list:
    """List all source monitors of a composite monitor."""
    monitor = await _get_monitor_or_404(monitor_id, current_user, db)
    if monitor.check_type != "composite":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This monitor is not a composite monitor",
        )
    rows = (
        await db.execute(
            select(CompositeMonitorMember).where(
                CompositeMonitorMember.composite_id == monitor_id
            )
        )
    ).scalars().all()
    return list(rows)


@router.post(
    "/{monitor_id}/composite-members",
    response_model=CompositeMonitorMemberOut,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("30/minute")
async def add_composite_member(
    request: Request,
    monitor_id: uuid.UUID,
    payload: CompositeMonitorMemberCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> object:
    """Add a source monitor to a composite monitor."""
    composite = await _get_monitor_or_404(monitor_id, current_user, db)
    if composite.check_type != "composite":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Target monitor is not a composite monitor",
        )
    if payload.monitor_id == monitor_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A composite monitor cannot reference itself",
        )

    member_monitor = await _get_monitor_or_404(payload.monitor_id, current_user, db)
    if member_monitor.check_type == "composite":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A composite monitor cannot be a member of another composite",
        )

    existing = (
        await db.execute(
            select(CompositeMonitorMember).where(
                CompositeMonitorMember.composite_id == monitor_id,
                CompositeMonitorMember.monitor_id == payload.monitor_id,
            )
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Member already added"
        )

    member = CompositeMonitorMember(
        composite_id=monitor_id,
        monitor_id=payload.monitor_id,
        weight=payload.weight,
        role=payload.role,
    )
    db.add(member)
    await db.flush()
    return member


@router.patch(
    "/{monitor_id}/composite-members/{member_id}",
    response_model=CompositeMonitorMemberOut,
)
@limiter.limit("30/minute")
async def update_composite_member(
    request: Request,
    monitor_id: uuid.UUID,
    member_id: uuid.UUID,
    payload: CompositeMonitorMemberCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> object:
    """Update weight or role of a composite member."""
    await _get_monitor_or_404(monitor_id, current_user, db)
    member = (
        await db.execute(
            select(CompositeMonitorMember).where(
                CompositeMonitorMember.id == member_id,
                CompositeMonitorMember.composite_id == monitor_id,
            )
        )
    ).scalar_one_or_none()
    if member is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")
    member.weight = payload.weight
    member.role = payload.role
    await db.flush()
    return member


@router.delete(
    "/{monitor_id}/composite-members/{member_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_composite_member(
    monitor_id: uuid.UUID,
    member_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Remove a source monitor from a composite monitor."""
    await _get_monitor_or_404(monitor_id, current_user, db)
    member = (
        await db.execute(
            select(CompositeMonitorMember).where(
                CompositeMonitorMember.id == member_id,
                CompositeMonitorMember.composite_id == monitor_id,
            )
        )
    ).scalar_one_or_none()
    if member is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")
    await db.delete(member)
