"""Public status page endpoints — no authentication required."""

import json
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
from whatisup.core.redis import redis_get_safe, redis_setex_safe
from whatisup.models.incident import IS_AVAILABILITY_INCIDENT, Incident
from whatisup.models.incident_update import IncidentUpdate
from whatisup.models.monitor import Monitor, MonitorGroup
from whatisup.models.status_subscription import StatusSubscription
from whatisup.services.stats import (
    compute_daily_history_bulk,
    compute_uptime,
    compute_uptime_bulk,
    fetch_latest_results,
)
from whatisup.services.status_subscription import send_confirmation_email

router = APIRouter(prefix="/public", tags=["public"])

# Public status pages are unauthenticated and rate-limited at 60 req/min, while
# their monitor payload costs a 90-day aggregation over the raw check_results
# table (~9.5 s measured on 4.9M rows — plan V2, constat n°3). Without a cache
# the endpoint is a trivial amplification vector, so the whole payload is
# memoised per group; 60 s of staleness is invisible on a 90-day history.
PUBLIC_MONITORS_CACHE_TTL = 60


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
@limiter.limit("60/minute")
async def get_public_monitors(
    request: Request, slug: str, db: AsyncSession = Depends(get_db)
) -> list[dict]:
    group = await _get_group_by_slug(slug, db)

    cache_key = f"whatisup:public:monitors:{group.id}"
    cached = await redis_get_safe(cache_key)
    if cached:
        return json.loads(cached)

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
        # Deliberately not cached: an empty page costs two indexed lookups, and
        # caching it would leave a freshly-populated page blank for a full TTL.
        return []

    monitor_ids = [m.id for m in monitors]

    # Batch-fetch latest result per monitor (N+1 avoidance, LATERAL on PostgreSQL)
    latest_by_monitor = await fetch_latest_results(db, monitor_ids)

    # Batch uptime + daily history: one SQL round-trip each for the whole
    # group instead of 2 queries per monitor (public endpoint, unauthenticated)
    uptime_bulk = await compute_uptime_bulk(db, monitor_ids, period_hours=24)
    history_bulk = await compute_daily_history_bulk(db, monitor_ids, days=90)

    results = []
    for m in monitors:
        uptime = uptime_bulk.get(str(m.id), {})
        latest = latest_by_monitor.get(m.id)

        # Daily history — 90 days
        raw_history = history_bulk.get(str(m.id), [])
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
                "uptime_24h": uptime.get("uptime_percent", 100.0),
                "avg_response_time_ms": uptime.get("avg_response_time_ms"),
                "current_status": latest.status.value if latest else None,
                "current_value": latest.final_url if latest else None,
                "last_checked_at": latest.checked_at.isoformat() if latest else None,
                "history_90d": history_90d,
            }
        )

    await redis_setex_safe(cache_key, PUBLIC_MONITORS_CACHE_TTL, json.dumps(results))
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
                    # C-4 — a status page speaks about service availability to
                    # people outside the tenant. "queue_depth above 1000" is an
                    # internal application signal; publishing it would leak
                    # implementation detail and read as an outage that isn't one.
                    IS_AVAILABILITY_INCIDENT,
                )
                .order_by(Incident.started_at.desc())
                # Bound the public payload — a flapping group can accumulate
                # hundreds of incidents over 30 days
                .limit(100)
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
                # Same reason as the 30-day list: a metric incident is not
                # public, so it must 404 here rather than be fetchable by id.
                IS_AVAILABILITY_INCIDENT,
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
    """Start a double opt-in subscription to a public status page.

    La page n'exige aucune authentification : n'importe qui peut soumettre
    l'adresse d'un tiers. L'abonnement naît donc inactif et ne le devient
    qu'après clic sur le lien envoyé à l'adresse elle-même.
    """
    group = await _get_group_by_slug(slug, db)
    email = payload.email

    existing = (
        await db.execute(
            select(StatusSubscription).where(
                StatusSubscription.group_id == group.id,
                StatusSubscription.email == email,
            )
        )
    ).scalar_one_or_none()

    if existing is not None:
        # Une inscription restée non confirmée peut être relancée : sinon un
        # mail perdu enfermerait l'adresse dans un état sans issue.
        if existing.confirmed_at is None:
            existing.confirm_token = secrets.token_urlsafe(32)
            await db.flush()
            await send_confirmation_email(existing, group)
        # Réponse identique dans tous les cas : ne pas révéler si l'adresse
        # est déjà abonnée (anti-énumération).
        return {"message": "Check your inbox to confirm the subscription."}

    sub = StatusSubscription(
        group_id=group.id,
        email=email,
        token=secrets.token_urlsafe(32),
        confirm_token=secrets.token_urlsafe(32),
    )
    db.add(sub)
    await db.flush()
    await send_confirmation_email(sub, group)
    return {"message": "Check your inbox to confirm the subscription."}


@router.get("/pages/{slug}/confirm")
@limiter.limit("10/minute")
async def confirm_status_subscription(
    request: Request,
    slug: str,
    token: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Activate a subscription from the link sent by e-mail (double opt-in)."""
    group = await _get_group_by_slug(slug, db)

    sub = (
        await db.execute(
            select(StatusSubscription).where(
                StatusSubscription.confirm_token == token,
                StatusSubscription.group_id == group.id,
            )
        )
    ).scalar_one_or_none()
    if sub is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invalid token")

    if sub.confirmed_at is None:
        sub.confirmed_at = datetime.now(UTC)
    # Le jeton ne sert qu'une fois : un lien qui traîne dans une boîte mail ne
    # doit pas pouvoir réactiver un abonnement supprimé depuis.
    sub.confirm_token = None
    return {"message": "Subscription confirmed."}


@router.get("/pages/{slug}/unsubscribe")
@limiter.limit("10/minute")
async def unsubscribe_status(
    request: Request,
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invalid token")
    await db.delete(sub)
    return {"message": "Unsubscribed."}
