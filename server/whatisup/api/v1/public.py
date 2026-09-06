"""Public status page endpoints — no authentication required."""

import html
import json
import secrets
import uuid
from collections import defaultdict
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from starlette.responses import Response

from whatisup.core.config import get_settings
from whatisup.core.database import get_db
from whatisup.core.limiter import limiter
from whatisup.core.redis import redis_get_safe, redis_setex_safe
from whatisup.models.incident import IS_AVAILABILITY_INCIDENT, Incident
from whatisup.models.incident_update import IncidentUpdate
from whatisup.models.maintenance import MaintenanceWindow
from whatisup.models.monitor import Monitor, MonitorGroup
from whatisup.models.probe import Probe
from whatisup.models.result import CheckResult
from whatisup.models.status_announcement import StatusAnnouncement
from whatisup.models.status_subscription import StatusSubscription
from whatisup.services.atom_feed import AtomEntry, render_atom_feed
from whatisup.services.network_verdict import _DOWN_STATUSES
from whatisup.services.stats import (
    compute_daily_history_bulk,
    compute_uptime,
    compute_uptime_bulk,
    fetch_latest_results,
)
from whatisup.services.status_subscription import send_confirmation_email

router = APIRouter(prefix="/public", tags=["public"])

# Plan V2, cap V2 3b — only these two verdicts are worth telling a visitor
# about. `service_down` needs no extra sentence (an open, unresolved incident
# already says "it's down"), and null/inconclusive means we don't actually
# know — publishing "inconclusive" would read as a category when it's really
# silence. Never widen this to expose the ASN/country identity itself: the
# *category* is public, the operator name and AS number stay authenticated-only.
_PUBLIC_VERDICTS = {"network_partition_asn", "network_partition_geo"}

# Public status pages are unauthenticated and rate-limited at 60 req/min, while
# their monitor payload costs a 90-day aggregation over the raw check_results
# table (~9.5 s measured on 4.9M rows — plan V2, constat n°3). Without a cache
# the endpoint is a trivial amplification vector, so the whole payload is
# memoised per group; 60 s of staleness is invisible on a 90-day history.
PUBLIC_MONITORS_CACHE_TTL = 60


# ── Badge SVG helper ──────────────────────────────────────────────


def _badge_svg(label: str, value: str, color: str) -> str:
    # `label`/`value` reach this f-string unescaped: today both call sites pass
    # literals ("uptime", a percentage), but the signature invites a monitor's
    # public name — html.escape() closes that off cheaply without pulling in
    # a real XML serializer for a two-value SVG (unlike the Atom feed below,
    # which does need one).
    safe_label = html.escape(label, quote=True)
    safe_value = html.escape(value, quote=True)
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
        f'    <text x="{label_w / 2}" y="15" fill="#010101" fill-opacity=".3">{safe_label}</text>\n'
        f'    <text x="{label_w / 2}" y="14">{safe_label}</text>\n'
        f'    <text x="{label_w + value_w / 2}" y="15"'
        f' fill="#010101" fill-opacity=".3">{safe_value}</text>\n'
        f'    <text x="{label_w + value_w / 2}" y="14">'
        f"{safe_value}</text>\n"
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


def _feed_monitor_name(monitor: Monitor | None) -> str:
    """Name a monitor the same way the rest of the public page will once
    ``Monitor.public_name`` exists (cap v2, 5c — not merged as of this lot):
    prefer it, fall back to the internal `name`, and degrade to plain `name`
    today without the column at all. Never the URL, TCP port, DNS record
    type or `check_type` — that inventory was closed off by 5c and a new
    endpoint must not reopen it (see module docstring / PR #417)."""
    if monitor is None:
        return "unknown monitor"
    return getattr(monitor, "public_name", None) or monitor.name


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

    now = datetime.now(UTC)

    # Cap v2, 5a — a scheduled/active maintenance window is a *fact*, not an
    # outage. Only the window and an optional operator-written message are
    # published; `name`/`description` were written assuming they were
    # internal (e.g. "migration PG16 prod-db-02") and must never appear here.
    # Scoped to this group only: its own group-wide windows, plus windows
    # targeting one of its own monitors — never a window on another group's
    # monitor. `ends_at >= now` keeps the list to current + upcoming, capped
    # so a heavy maintenance schedule can't inflate the payload.
    maintenance_conditions = [MaintenanceWindow.group_id == group.id]
    if monitor_ids:
        maintenance_conditions.append(MaintenanceWindow.monitor_id.in_(monitor_ids))
    window_rows = (
        (
            await db.execute(
                select(MaintenanceWindow)
                .where(or_(*maintenance_conditions), MaintenanceWindow.ends_at >= now)
                .order_by(MaintenanceWindow.starts_at.asc())
                .limit(20)
            )
        )
        .scalars()
        .all()
    )
    maintenance_windows = [
        {
            "id": str(w.id),
            "monitor_id": str(w.monitor_id) if w.monitor_id else None,
            "starts_at": w.starts_at.isoformat(),
            "ends_at": w.ends_at.isoformat(),
            "message": w.public_message,
        }
        for w in window_rows
    ]

    # Incidents des 30 derniers jours
    cutoff_30d = now - timedelta(days=30)

    # Cap v2, 5b — human-authored announcements, scoped to this group only.
    # Deliberately NOT `Incident`: see models/status_announcement.py. Active
    # announcements always show; a closed one stays visible for the same
    # 30-day window as incidents so it isn't presented as active but also
    # doesn't vanish the moment it's closed. `selectinload` keeps this a
    # single extra query (IN clause) regardless of how many announcements
    # come back — no per-announcement round trip.
    announcement_rows = (
        (
            await db.execute(
                select(StatusAnnouncement)
                .options(selectinload(StatusAnnouncement.updates))
                .where(
                    StatusAnnouncement.group_id == group.id,
                    or_(
                        StatusAnnouncement.ended_at.is_(None),
                        StatusAnnouncement.ended_at >= cutoff_30d,
                    ),
                )
                .order_by(StatusAnnouncement.started_at.desc())
                .limit(50)
            )
        )
        .scalars()
        .unique()
        .all()
    )
    announcements = [
        {
            "id": str(a.id),
            "title": a.title,
            "status": a.status.value,
            "started_at": a.started_at.isoformat(),
            "ended_at": a.ended_at.isoformat() if a.ended_at else None,
            "is_active": a.ended_at is None,
            "updates": [
                {
                    "id": str(u.id),
                    "status": u.status.value,
                    "message": u.message,
                    "created_by_name": u.created_by_name,
                    "created_at": u.created_at.isoformat(),
                }
                for u in a.updates
                if u.is_public
            ],
        }
        for a in announcement_rows
    ]

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

    # cap V2 3b — reachability counters ("joignable depuis N de nos M points
    # d'observation"). Only meaningful for *open* incidents: the count reflects
    # the current state of the fleet, and a resolved incident showing today's
    # count would silently misdescribe the moment the outage happened (same
    # reasoning that ruled out backfilling historical incidents at step 1).
    # One grouped query for every such incident, not one per incident — the
    # list is capped at 100 and open partition-verdict incidents are rare.
    #
    # Deliberately re-derived from live CheckResults rather than from
    # ``Incident.affected_probe_ids``: that column is populated inconsistently
    # across the two incident-opening paths (legacy pipeline vs Health Engine
    # bridge — one leaves it empty), so it cannot be trusted for a number shown
    # to an unauthenticated visitor. Mirrors the sampling ``classify_network_verdict``
    # itself uses (latest CheckResult per active probe for the monitor).
    open_partition_monitor_ids = {
        inc.monitor_id
        for inc in incident_rows
        if not inc.is_resolved and inc.network_verdict in _PUBLIC_VERDICTS
    }
    reachability: dict[uuid.UUID, tuple[int, int]] = {}
    if open_partition_monitor_ids:
        latest_probe_subq = (
            select(
                CheckResult.monitor_id,
                CheckResult.probe_id,
                func.max(CheckResult.checked_at).label("max_at"),
            )
            .where(
                CheckResult.monitor_id.in_(open_partition_monitor_ids),
                CheckResult.probe_id.isnot(None),
            )
            .group_by(CheckResult.monitor_id, CheckResult.probe_id)
            .subquery()
        )
        latest_rows = (
            await db.execute(
                select(CheckResult.monitor_id, CheckResult.status)
                .join(Probe, Probe.id == CheckResult.probe_id)
                .join(
                    latest_probe_subq,
                    (CheckResult.monitor_id == latest_probe_subq.c.monitor_id)
                    & (CheckResult.probe_id == latest_probe_subq.c.probe_id)
                    & (CheckResult.checked_at == latest_probe_subq.c.max_at),
                )
                .where(Probe.is_active.is_(True))
            )
        ).all()
        totals: dict[uuid.UUID, int] = defaultdict(int)
        reachable: dict[uuid.UUID, int] = defaultdict(int)
        for monitor_id, check_status in latest_rows:
            totals[monitor_id] += 1
            if check_status not in _DOWN_STATUSES:
                reachable[monitor_id] += 1
        reachability = {mid: (reachable[mid], total) for mid, total in totals.items()}

    incidents_30d = []
    for inc in incident_rows:
        mon = monitor_by_id.get(inc.monitor_id)
        duration_minutes: int | None = None
        if inc.duration_seconds is not None:
            duration_minutes = inc.duration_seconds // 60
        elif inc.resolved_at is not None:
            duration_minutes = int((inc.resolved_at - inc.started_at).total_seconds() // 60)
        item = {
            "id": str(inc.id),
            "monitor_id": str(inc.monitor_id),
            "monitor_name": mon.name if mon else None,
            "started_at": inc.started_at.isoformat(),
            "resolved_at": inc.resolved_at.isoformat() if inc.resolved_at else None,
            "duration_minutes": duration_minutes,
            "scope": inc.scope.value,
            "is_resolved": inc.is_resolved,
        }
        # A number is worse than no number: a resolved incident only ever gets
        # the verdict category, never counters computed from the fleet's
        # *current* state (rule below). `service_down` and inconclusive/null
        # verdicts get nothing at all — see `_PUBLIC_VERDICTS` above.
        if inc.network_verdict in _PUBLIC_VERDICTS:
            item["network_verdict"] = inc.network_verdict
            if not inc.is_resolved:
                counts = reachability.get(inc.monitor_id)
                if counts and counts[1] > 0:
                    item["reachable_probes"] = counts[0]
                    item["total_probes"] = counts[1]
        incidents_30d.append(item)

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
        "maintenance_windows": maintenance_windows,
        "announcements": announcements,
    }


# Cap v2, 5d — an Atom feed is table stakes for a status page (Statuspage,
# Better Stack and Instatus all ship one); nothing here offered a subscriber
# anything to follow before this endpoint. Same cache trade-off as the two
# endpoints above: unauthenticated, so it is memoised per group.
PUBLIC_FEED_CACHE_TTL = 60
# Bounded like `incidents_30d` above — an unauthenticated endpoint with an
# unbounded feed is an amplification vector, not a feature.
PUBLIC_FEED_MAX_ENTRIES = 100


@router.get("/pages/{slug}/feed.atom")
@limiter.limit("60/minute")
async def get_public_atom_feed(
    request: Request, slug: str, db: AsyncSession = Depends(get_db)
) -> Response:
    """Public Atom 1.0 feed for a status page: availability incidents (5c
    scope — never a metric incident), announcements with their update thread
    (5b), and published maintenance windows (5a). One entry per *object*, not
    per state change — `id` is stable and `updated` moves with the object so
    a feed reader can dedupe instead of re-surfacing every edit as new.

    Never republishes what 5c closed off: a monitor is named (public name,
    falling back to its internal name), never addressed by URL, TCP port,
    DNS record type or check type.
    """
    group = await _get_group_by_slug(slug, db)

    cache_key = f"whatisup:public:feed:{group.id}"
    cached = await redis_get_safe(cache_key)
    if cached:
        return Response(content=cached, media_type="application/atom+xml; charset=utf-8")

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

    now = datetime.now(UTC)
    cutoff_30d = now - timedelta(days=30)

    settings = get_settings()
    base = str(settings.public_base_url).rstrip("/")
    page_url = f"{base}/status/{slug}"

    entries: list[AtomEntry] = []

    # ── Incidents — availability only. A metric incident (C-4) is an
    # internal application signal, never published here, same restriction as
    # `incidents_30d` above. ──
    if monitor_ids:
        incident_rows = (
            (
                await db.execute(
                    select(Incident)
                    .where(
                        Incident.monitor_id.in_(monitor_ids),
                        Incident.started_at >= cutoff_30d,
                        IS_AVAILABILITY_INCIDENT,
                    )
                    .order_by(Incident.started_at.desc())
                    .limit(PUBLIC_FEED_MAX_ENTRIES)
                )
            )
            .scalars()
            .all()
        )
        for inc in incident_rows:
            monitor_name = _feed_monitor_name(monitor_by_id.get(inc.monitor_id))
            # No `updated_at` column on `Incident` — resolution is the only
            # modification a public reader is told about, so it doubles as
            # the Atom `updated` timestamp (dedup breaks otherwise: an
            # incident that later resolves must not look unchanged).
            updated = inc.resolved_at or inc.started_at
            if inc.is_resolved:
                title = f"{monitor_name}: resolved"
                summary = f"{monitor_name} recovered."
                if inc.duration_seconds is not None:
                    summary += f" Duration: {inc.duration_seconds // 60} min."
            else:
                title = f"{monitor_name}: ongoing incident"
                summary = f"{monitor_name} is currently experiencing an incident."
                # Same public restriction as `incidents_30d`: only the two
                # network-partition verdicts are ever named, never the
                # ASN/country identity behind them.
                if inc.network_verdict in _PUBLIC_VERDICTS:
                    summary += (
                        " Classified as a network partition, not necessarily a service outage."
                    )
            entries.append(
                AtomEntry(
                    entry_id=f"urn:whatisup:incident:{inc.id}",
                    title=title,
                    updated=updated,
                    published=inc.started_at,
                    summary=summary,
                    link=page_url,
                )
            )

    # ── Announcements (5b) — the update thread is folded into the entry's
    # summary rather than emitted as separate entries: one announcement is
    # one narrative, and a reader dedupes on the announcement, not each post
    # in its thread. `updated_at` (TimestampMixin) already bumps on title
    # edits, new posts and close (see api/v1/status_announcements.py). ──
    announcement_rows = (
        (
            await db.execute(
                select(StatusAnnouncement)
                .options(selectinload(StatusAnnouncement.updates))
                .where(
                    StatusAnnouncement.group_id == group.id,
                    or_(
                        StatusAnnouncement.ended_at.is_(None),
                        StatusAnnouncement.ended_at >= cutoff_30d,
                    ),
                )
                .order_by(StatusAnnouncement.started_at.desc())
                .limit(PUBLIC_FEED_MAX_ENTRIES)
            )
        )
        .scalars()
        .unique()
        .all()
    )
    for ann in announcement_rows:
        public_posts = [u for u in ann.updates if u.is_public]
        summary = "\n\n".join(f"[{u.status.value}] {u.message}" for u in public_posts) or ann.title
        entries.append(
            AtomEntry(
                entry_id=f"urn:whatisup:announcement:{ann.id}",
                title=ann.title,
                updated=ann.updated_at,
                published=ann.started_at,
                summary=summary,
                link=page_url,
            )
        )

    # ── Maintenance windows (5a) — same group scoping as the block above,
    # widened to also cover windows that ended within the last 30 days: the
    # `/status` endpoint only needs current+upcoming, but a feed reader that
    # last polled before a short window both started and ended would
    # otherwise never see it. ──
    maintenance_conditions = [MaintenanceWindow.group_id == group.id]
    if monitor_ids:
        maintenance_conditions.append(MaintenanceWindow.monitor_id.in_(monitor_ids))
    window_rows = (
        (
            await db.execute(
                select(MaintenanceWindow)
                .where(or_(*maintenance_conditions), MaintenanceWindow.ends_at >= cutoff_30d)
                .order_by(MaintenanceWindow.starts_at.desc())
                .limit(PUBLIC_FEED_MAX_ENTRIES)
            )
        )
        .scalars()
        .all()
    )
    for window in window_rows:
        # `name`/`description` are internal (see models/maintenance.py) —
        # only the operator-written `public_message` is ever shown, exactly
        # like the `/status` endpoint above.
        summary = window.public_message or (
            f"Scheduled maintenance from {window.starts_at.isoformat()} "
            f"to {window.ends_at.isoformat()}."
        )
        entries.append(
            AtomEntry(
                entry_id=f"urn:whatisup:maintenance:{window.id}",
                title="Scheduled maintenance",
                updated=window.updated_at,
                published=window.created_at,
                summary=summary,
                link=page_url,
            )
        )

    # Three independently-capped sources can still exceed the feed's own
    # cap once merged — sort by most-recently-updated and truncate.
    entries.sort(key=lambda e: e.updated, reverse=True)
    entries = entries[:PUBLIC_FEED_MAX_ENTRIES]

    feed_xml = render_atom_feed(
        feed_id=f"urn:whatisup:statuspage:{group.id}",
        title=f"{group.public_title or group.name} — Status",
        self_url=f"{base}/api/v1/public/pages/{slug}/feed.atom",
        alternate_url=page_url,
        entries=entries,
    )

    await redis_setex_safe(cache_key, PUBLIC_FEED_CACHE_TTL, feed_xml)
    return Response(content=feed_xml, media_type="application/atom+xml; charset=utf-8")


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
