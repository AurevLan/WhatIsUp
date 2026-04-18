"""Public status page endpoints — no authentication required."""

import secrets
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import Response

from whatisup.core.database import get_db
from whatisup.core.limiter import limiter
from whatisup.models.incident import Incident
from whatisup.models.incident_update import IncidentUpdate
from whatisup.models.monitor import Monitor, MonitorGroup
from whatisup.models.result import CheckResult
from whatisup.models.status_subscription import StatusSubscription
from whatisup.services.stats import compute_daily_history, compute_uptime, latest_results_subq

router = APIRouter(prefix="/public", tags=["public"])


# ── Badge SVG helper ──────────────────────────────────────────────


def _badge_svg(label: str, value: str, color: str) -> str:
    label_w = len(label) * 6.5 + 12
    value_w = len(value) * 6.5 + 12
    total_w = label_w + value_w
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{total_w}" height="20">\n'
        f'  <linearGradient id="a" x2="0" y2="100%">\n'
        f'    <stop offset="0" stop-color="#bbb" stop-opacity=".1"/>\n'
        f'    <stop offset="1" stop-opacity=".1"/>\n'
        f"  </linearGradient>\n"
        f'  <rect rx="3" width="{total_w}" height="20" fill="#555"/>\n'
        f'  <rect rx="3" x="{label_w}" width="{value_w}" height="20" fill="{color}"/>\n'
        f'  <rect rx="3" width="{total_w}" height="20" fill="url(#a)"/>\n'
        f'  <g fill="#fff" text-anchor="middle"'
        f' font-family="DejaVu Sans,Verdana,Geneva,sans-serif" font-size="11">\n'
        f'    <text x="{label_w / 2}" y="15" fill="#010101" fill-opacity=".3">{label}</text>\n'
        f'    <text x="{label_w / 2}" y="14">{label}</text>\n'
        f'    <text x="{label_w + value_w / 2}" y="15"'
        f' fill="#010101" fill-opacity=".3">{value}</text>\n'
        f'    <text x="{label_w + value_w / 2}" y="14">'
        f"{value}</text>\n"
        f"  </g>\n"
        f"</svg>"
    )


class SubscribeRequest(BaseModel):
    email: EmailStr


async def _get_group_by_slug(slug: str, db: AsyncSession) -> MonitorGroup:
    group = (
        await db.execute(select(MonitorGroup).where(MonitorGroup.public_slug == slug))
    ).scalar_one_or_none()
    if group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Status page not found")
    return group


@router.get("/badge/{slug}/{monitor_name}")
@limiter.limit("120/minute")
async def get_uptime_badge(
    slug: str,
    monitor_name: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Return a shields.io-style SVG badge with 24h uptime for a monitor."""
    group = await _get_group_by_slug(slug, db)

    monitor = (
        await db.execute(
            select(Monitor).where(
                Monitor.group_id == group.id,
                func.lower(Monitor.name) == monitor_name.lower(),
            )
        )
    ).scalar_one_or_none()

    if monitor is None:
        svg = _badge_svg("uptime", "not found", "#9f9f9f")
        return Response(
            content=svg,
            media_type="image/svg+xml",
            headers={"Cache-Control": "public, max-age=60"},
        )

    uptime = await compute_uptime(db, monitor.id, period_hours=24)
    pct = uptime.uptime_percent

    if pct >= 99.0:
        color = "#4c1"
    elif pct >= 95.0:
        color = "#dfb317"
    elif pct >= 90.0:
        color = "#fe7d37"
    else:
        color = "#e05d44"

    svg = _badge_svg("uptime", f"{pct:.2f}%", color)
    return Response(
        content=svg,
        media_type="image/svg+xml",
        headers={"Cache-Control": "public, max-age=60"},
    )


@router.get("/pages/{slug}")
@limiter.limit("60/minute")
async def get_public_page(request: Request, slug: str, db: AsyncSession = Depends(get_db)) -> dict:
    group = await _get_group_by_slug(slug, db)
    return {
        "name": group.name,
        "slug": slug,
        "description": group.description,
        "custom_logo_url": group.custom_logo_url,
        "accent_color": group.accent_color,
        "announcement_banner": group.announcement_banner,
        "public_title": group.public_title,
        "public_description": group.public_description,
        "public_logo_url": group.public_logo_url,
        "public_accent_color": group.public_accent_color,
        "public_custom_css": group.public_custom_css,
    }


@router.get("/pages/{slug}/monitors")
async def get_public_monitors(slug: str, db: AsyncSession = Depends(get_db)) -> list[dict]:
    group = await _get_group_by_slug(slug, db)

    monitors = (
        (
            await db.execute(
                select(Monitor).where(
                    Monitor.group_id == group.id,
                    Monitor.enabled.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )

    if not monitors:
        return []

    monitor_ids = [m.id for m in monitors]

    # Batch-fetch latest result per monitor (N+1 avoidance)
    subq = latest_results_subq(
        CheckResult.monitor_id.in_(monitor_ids),
        group_col=CheckResult.monitor_id,
    )
    latest_rows = (
        (
            await db.execute(
                select(CheckResult).join(
                    subq,
                    (CheckResult.monitor_id == subq.c.monitor_id)
                    & (CheckResult.checked_at == subq.c.max_at),
                )
            )
        )
        .scalars()
        .all()
    )
    latest_by_monitor = {r.monitor_id: r for r in latest_rows}

    results = []
    for m in monitors:
        uptime = await compute_uptime(db, m.id, period_hours=24)
        latest = latest_by_monitor.get(m.id)

        # Daily history — 90 days
        raw_history = await compute_daily_history(db, m.id, days=90)
        history_by_date = {entry["date"]: entry for entry in raw_history}

        history_90d = []
        today = datetime.now(UTC).date()
        for day_offset in range(89, -1, -1):
            day = today - timedelta(days=day_offset)
            day_str = day.isoformat()
            if day_str in history_by_date:
                entry = history_by_date[day_str]
                total = entry["total"]
                up = entry["up_count"]
                failed = total - up
                if total == 0:
                    day_status = "no_data"
                elif failed / total > 0.30:
                    day_status = "down"
                elif failed / total > 0.01:
                    day_status = "degraded"
                else:
                    day_status = "up"
                history_90d.append(
                    {
                        "date": day_str,
                        "status": day_status,
                        "uptime_pct": entry["uptime_percent"],
                    }
                )
            else:
                history_90d.append(
                    {
                        "date": day_str,
                        "status": "no_data",
                        "uptime_pct": None,
                    }
                )

        results.append(
            {
                "id": str(m.id),
                "name": m.name,
                "url": m.url,
                "check_type": m.check_type,
                "tcp_port": m.tcp_port,
                "dns_record_type": m.dns_record_type,
                "uptime_24h": uptime.uptime_percent,
                "avg_response_time_ms": uptime.avg_response_time_ms,
                "current_status": latest.status.value if latest else None,
                "current_value": latest.final_url if latest else None,
                "last_checked_at": latest.checked_at.isoformat() if latest else None,
                "history_90d": history_90d,
            }
        )
    return results


@router.get("/pages/{slug}/status")
@limiter.limit("60/minute")
async def get_public_status(
    request: Request, slug: str, db: AsyncSession = Depends(get_db)
) -> dict:
    """Enriched status: page info + components + incidents_30d."""
    group = await _get_group_by_slug(slug, db)

    monitors = (
        (
            await db.execute(
                select(Monitor).where(
                    Monitor.group_id == group.id,
                    Monitor.enabled.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )

    monitor_ids = [m.id for m in monitors]
    monitor_by_id = {m.id: m for m in monitors}

    # Incidents des 30 derniers jours
    cutoff_30d = datetime.now(UTC) - timedelta(days=30)
    incident_rows = (
        (
            await db.execute(
                select(Incident)
                .where(
                    Incident.monitor_id.in_(monitor_ids),
                    Incident.started_at >= cutoff_30d,
                )
                .order_by(Incident.started_at.desc())
            )
        )
        .scalars()
        .all()
    )

    incidents_30d = []
    for inc in incident_rows:
        mon = monitor_by_id.get(inc.monitor_id)
        duration_minutes: int | None = None
        if inc.duration_seconds is not None:
            duration_minutes = inc.duration_seconds // 60
        elif inc.resolved_at is not None:
            duration_minutes = int((inc.resolved_at - inc.started_at).total_seconds() // 60)
        incidents_30d.append(
            {
                "id": str(inc.id),
                "monitor_id": str(inc.monitor_id),
                "monitor_name": mon.name if mon else None,
                "started_at": inc.started_at.isoformat(),
                "resolved_at": inc.resolved_at.isoformat() if inc.resolved_at else None,
                "duration_minutes": duration_minutes,
                "scope": inc.scope.value,
                "is_resolved": inc.is_resolved,
            }
        )

    return {
        "name": group.name,
        "slug": slug,
        "description": group.description,
        "custom_logo_url": group.custom_logo_url,
        "accent_color": group.accent_color,
        "announcement_banner": group.announcement_banner,
        "public_title": group.public_title,
        "public_description": group.public_description,
        "public_logo_url": group.public_logo_url,
        "public_accent_color": group.public_accent_color,
        "public_custom_css": group.public_custom_css,
        "incidents_30d": incidents_30d,
    }


@router.get("/pages/{slug}/incidents/{incident_id}/updates")
@limiter.limit("30/minute")
async def get_public_incident_updates(
    slug: str,
    incident_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Public endpoint: list updates for a specific incident on a status page."""
    group = await _get_group_by_slug(slug, db)

    # Verify the incident belongs to this group (single JOIN query)
    row = (
        await db.execute(
            select(Incident)
            .join(Monitor, Monitor.id == Incident.monitor_id)
            .where(
                Incident.id == incident_id,
                Monitor.group_id == group.id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Incident not found on this page")

    updates = (
        (
            await db.execute(
                select(IncidentUpdate)
                .where(
                    IncidentUpdate.incident_id == incident_id,
                    IncidentUpdate.is_public.is_(True),
                )
                .order_by(IncidentUpdate.created_at.asc())
            )
        )
        .scalars()
        .all()
    )

    return [
        {
            "id": str(u.id),
            "status": u.status.value,
            "message": u.message,
            "created_by_name": u.created_by_name,
            "created_at": u.created_at.isoformat(),
        }
        for u in updates
    ]


@router.post("/pages/{slug}/subscribe", status_code=201)
@limiter.limit("5/minute")
async def subscribe_status(
    slug: str,
    payload: SubscribeRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Subscribe an email address to status page notifications."""
    group = await _get_group_by_slug(slug, db)

    email = payload.email
    # Vérifier si déjà inscrit
    existing = (
        await db.execute(
            select(StatusSubscription).where(
                StatusSubscription.group_id == group.id,
                StatusSubscription.email == email,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        # Répondre 200 sans révéler si l'email existe (anti-enumeration)
        return {"message": "Inscription confirmée"}

    token = secrets.token_urlsafe(32)
    sub = StatusSubscription(group_id=group.id, email=email, token=token)
    db.add(sub)
    return {"message": "Inscription confirmée"}


@router.get("/pages/{slug}/unsubscribe")
async def unsubscribe_status(
    slug: str,
    token: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Unsubscribe from status page notifications via token."""
    # Vérifier que le slug correspond bien (évite l'exploitation cross-group)
    group = await _get_group_by_slug(slug, db)

    sub = (
        await db.execute(
            select(StatusSubscription).where(
                StatusSubscription.token == token,
                StatusSubscription.group_id == group.id,
            )
        )
    ).scalar_one_or_none()
    if sub is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Token invalide")
    await db.delete(sub)
    return {"message": "Désabonnement effectué"}
