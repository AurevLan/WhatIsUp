"""Per-monitor incidents and post-mortem generation."""

import logging
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.api.deps import (
    get_current_user,
)
from whatisup.api.v1.monitors._common import _get_monitor_or_404
from whatisup.core.database import get_db
from whatisup.core.limiter import limiter
from whatisup.models.annotation import MonitorAnnotation
from whatisup.models.result import CheckResult
from whatisup.models.user import User
from whatisup.schemas.incident import IncidentOut

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/monitors", tags=["monitors"])


@router.get("/{monitor_id}/incidents", response_model=list[IncidentOut])
@limiter.limit("60/minute")
async def get_incidents(
    request: Request,
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
@limiter.limit("30/minute")
async def get_postmortem(
    request: Request,
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incident not found")

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
        dur_label = "in progress"
        downtime_minutes = round((now_utc - incident.started_at).total_seconds() / 60, 1)
        resolved_str = "_in progress_"

    started_str = incident.started_at.strftime("%Y-%m-%d %H:%M UTC")

    # Construction de la chronologie
    timeline_rows = [
        f"| {incident.started_at.strftime('%H:%M UTC')}"
        f" | ❌ Incident opened — {incident.scope.value} |"
    ]
    for evt, ch_name in alert_events_rows:
        icon = "📧" if evt.status.value == "sent" else "⚠️"
        timeline_rows.append(
            f"| {evt.sent_at.strftime('%H:%M UTC')} | {icon} Alert sent via {ch_name} |"
        )
    if incident.resolved_at:
        timeline_rows.append(
            f"| {incident.resolved_at.strftime('%H:%M UTC')} | ✅ Incident resolved |"
        )
    timeline_md = "\n".join(timeline_rows)

    # Annotations markdown
    if annotations_rows:
        ann_lines = "\n".join(
            f"- **{a.annotated_at.strftime('%H:%M UTC')}** — {a.content}"
            + (f" _(by {a.created_by})_" if a.created_by else "")
            for a in annotations_rows
        )
    else:
        ann_lines = "_No annotations in this period._"

    markdown = f"""# Post-mortem: {monitor.name}

**Duration**: {started_str} → {resolved_str} ({dur_label})
**Impact**: {downtime_minutes} minutes of downtime

## Timeline
| Time | Event |
|------|-------|
{timeline_md}

## Metrics during the incident
- Checks performed: {total_checks}
- Failure rate: {failure_pct}%
- Average response time: {avg_rt if avg_rt is not None else "—"}ms

## Corrective actions
<!-- To be filled in -->

## Annotations
{ann_lines}
"""

    return {
        "content": markdown.strip(),
        "generated_at": now_utc.isoformat(),
    }
