"""Incident update endpoints — timeline of status updates posted on an incident."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, select
from sqlalchemy import update as sql_update
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.api.deps import build_access_filter, get_current_user, get_user_team_ids
from whatisup.core.database import get_db
from whatisup.core.limiter import limiter
from whatisup.models.incident import Incident
from whatisup.models.incident_update import IncidentUpdate
from whatisup.models.monitor import Monitor
from whatisup.models.probe import Probe
from whatisup.models.result import CheckResult, CheckStatus
from whatisup.models.user import User
from whatisup.schemas.incident import IncidentOut, IncidentUpdateCreate, IncidentUpdateOut

router = APIRouter(prefix="/incidents", tags=["incidents"])


async def _get_incident_for_user(
    incident_id: uuid.UUID,
    current_user: User,
    db: AsyncSession,
) -> Incident:
    """Fetch incident and verify the current user owns the monitor it belongs to."""
    incident = (
        await db.execute(select(Incident).where(Incident.id == incident_id))
    ).scalar_one_or_none()
    if incident is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incident not found")

    if not current_user.is_superadmin:
        from whatisup.api.deps import check_resource_access

        monitor = (
            await db.execute(
                select(Monitor).where(Monitor.id == incident.monitor_id)
            )
        ).scalar_one_or_none()
        if monitor is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Monitor not found")
        await check_resource_access(monitor, current_user, db)

    return incident


@router.get("/{incident_id}/updates", response_model=list[IncidentUpdateOut])
@limiter.limit("60/minute")
async def list_incident_updates(
    request: Request,
    incident_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list:
    await _get_incident_for_user(incident_id, current_user, db)
    updates = (
        await db.execute(
            select(IncidentUpdate)
            .where(IncidentUpdate.incident_id == incident_id)
            .order_by(IncidentUpdate.created_at.asc())
        )
    ).scalars().all()
    return list(updates)


@router.post("/{incident_id}/updates", response_model=IncidentUpdateOut, status_code=201)
@limiter.limit("30/minute")
async def create_incident_update(
    request: Request,
    incident_id: uuid.UUID,
    body: IncidentUpdateCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> IncidentUpdate:
    await _get_incident_for_user(incident_id, current_user, db)

    update = IncidentUpdate(
        incident_id=incident_id,
        created_by_id=current_user.id,
        created_by_name=current_user.email,
        status=body.status,
        message=body.message,
        is_public=body.is_public,
        created_at=datetime.now(UTC),
    )
    db.add(update)
    await db.flush()
    await db.refresh(update)
    return update


@router.delete("/{incident_id}/updates/{update_id}", status_code=204)
@limiter.limit("30/minute")
async def delete_incident_update(
    request: Request,
    incident_id: uuid.UUID,
    update_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await _get_incident_for_user(incident_id, current_user, db)

    update = (
        await db.execute(
            select(IncidentUpdate).where(
                IncidentUpdate.id == update_id,
                IncidentUpdate.incident_id == incident_id,
            )
        )
    ).scalar_one_or_none()
    if update is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Update not found")

    await db.delete(update)


@router.post("/{incident_id}/ack", response_model=IncidentOut)
@limiter.limit("30/minute")
async def acknowledge_incident(
    request: Request,
    incident_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Incident:
    incident = await _get_incident_for_user(incident_id, current_user, db)
    if incident.resolved_at is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot ack a resolved incident"
        )
    incident.acked_at = datetime.now(UTC)
    incident.acked_by_id = current_user.id
    await db.flush()
    return _incident_to_out(incident)


class BulkAckRequest(BaseModel):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=200)


class BulkAckResponse(BaseModel):
    affected: int


@router.post("/bulk-ack", response_model=BulkAckResponse)
@limiter.limit("20/minute")
async def bulk_ack_incidents(
    request: Request,
    payload: BulkAckRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Acknowledge multiple open incidents in a single round-trip.

    Resolved incidents in the payload are silently skipped. Access is enforced
    by joining incidents to the monitors the user can reach.
    """
    if current_user.is_superadmin:
        access_clause = Incident.id.in_(payload.ids)
    else:
        # Resolve the set of monitor IDs the caller can act on, then filter
        # incidents accordingly. Two queries beats inline join-update.
        team_ids = await get_user_team_ids(current_user, db)
        accessible_monitors = (
            await db.execute(
                select(Monitor.id).where(build_access_filter(Monitor, current_user, team_ids))
            )
        ).scalars().all()
        access_clause = and_(
            Incident.id.in_(payload.ids),
            Incident.monitor_id.in_(accessible_monitors),
        )

    now = datetime.now(UTC)
    result = await db.execute(
        sql_update(Incident)
        .where(access_clause, Incident.resolved_at.is_(None), Incident.acked_at.is_(None))
        .values(acked_at=now, acked_by_id=current_user.id)
    )
    return {"affected": result.rowcount}


class SnoozeRequest(BaseModel):
    duration_minutes: int = Field(ge=5, le=1440)  # 5 min — 24 h


@router.post("/{incident_id}/snooze", response_model=IncidentOut)
@limiter.limit("30/minute")
async def snooze_incident(
    request: Request,
    incident_id: uuid.UUID,
    body: SnoozeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Incident:
    """Suppress renotify dispatches for a bounded duration (T1-04).

    Distinct from /ack which is open-ended. Snooze auto-expires once
    ``snooze_until`` is in the past — the next renotify cycle picks the
    incident back up.
    """
    incident = await _get_incident_for_user(incident_id, current_user, db)
    if incident.resolved_at is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot snooze a resolved incident",
        )
    incident.snooze_until = datetime.now(UTC) + timedelta(minutes=body.duration_minutes)
    await db.flush()
    return _incident_to_out(incident)


@router.post("/{incident_id}/unsnooze", response_model=IncidentOut)
@limiter.limit("30/minute")
async def unsnooze_incident(
    request: Request,
    incident_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Incident:
    incident = await _get_incident_for_user(incident_id, current_user, db)
    incident.snooze_until = None
    await db.flush()
    return _incident_to_out(incident)


@router.post("/{incident_id}/unack", response_model=IncidentOut)
@limiter.limit("30/minute")
async def unacknowledge_incident(
    request: Request,
    incident_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Incident:
    incident = await _get_incident_for_user(incident_id, current_user, db)
    incident.acked_at = None
    incident.acked_by_id = None
    await db.flush()
    return _incident_to_out(incident)


# ── V2-02-06 — Incident playback timeline ────────────────────────────────────


class IncidentTimelinePoint(BaseModel):
    """One per-probe sample on the incident timeline."""

    checked_at: datetime
    probe_id: uuid.UUID
    probe_name: str | None = None
    probe_lat: float | None = None
    probe_lng: float | None = None
    probe_asn: int | None = None
    probe_country: str | None = None
    status: str  # CheckStatus value: up | down | timeout | error
    response_time_ms: float | None = None


class IncidentTimelineOut(BaseModel):
    incident_id: uuid.UUID
    started_at: datetime
    resolved_at: datetime | None
    points: list[IncidentTimelinePoint]


@router.get("/{incident_id}/timeline", response_model=IncidentTimelineOut)
@limiter.limit("30/minute")
async def incident_timeline(
    request: Request,
    incident_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> IncidentTimelineOut:
    """Return per-probe CheckResults bracketing the incident, for map playback.

    Includes a 5-minute grace window before ``started_at`` and after
    ``resolved_at`` so the UI can show the last UP state and the recovery.
    Capped at 2000 points to keep payload bounded.
    """
    incident = await _get_incident_for_user(incident_id, current_user, db)

    grace = timedelta(minutes=5)
    window_start = incident.started_at - grace
    window_end = (incident.resolved_at or datetime.now(UTC)) + grace

    rows = (
        (
            await db.execute(
                select(CheckResult, Probe)
                .join(Probe, CheckResult.probe_id == Probe.id)
                .where(
                    CheckResult.monitor_id == incident.monitor_id,
                    CheckResult.checked_at >= window_start,
                    CheckResult.checked_at <= window_end,
                )
                .order_by(CheckResult.checked_at.asc())
                .limit(2000)
            )
        )
        .all()
    )

    points = [
        IncidentTimelinePoint(
            checked_at=cr.checked_at,
            probe_id=cr.probe_id,
            probe_name=p.name,
            probe_lat=p.latitude,
            probe_lng=p.longitude,
            probe_asn=p.asn,
            probe_country=(p.location_name or "").split(",", 1)[0] or None,
            status=cr.status.value if isinstance(cr.status, CheckStatus) else str(cr.status),
            response_time_ms=cr.response_time_ms,
        )
        for cr, p in rows
    ]

    return IncidentTimelineOut(
        incident_id=incident.id,
        started_at=incident.started_at,
        resolved_at=incident.resolved_at,
        points=points,
    )


def _incident_to_out(inc: Incident) -> dict:
    """Build IncidentOut-compatible dict with computed SLA metrics."""
    mttd = None
    if inc.first_failure_at and inc.started_at:
        mttd = max(0, int((inc.started_at - inc.first_failure_at).total_seconds()))
    return {
        "id": inc.id,
        "monitor_id": inc.monitor_id,
        "started_at": inc.started_at,
        "resolved_at": inc.resolved_at,
        "duration_seconds": inc.duration_seconds,
        "scope": inc.scope,
        "affected_probe_ids": inc.affected_probe_ids,
        "dependency_suppressed": inc.dependency_suppressed,
        "group_id": inc.group_id,
        "acked_at": inc.acked_at,
        "acked_by_id": inc.acked_by_id,
        "snooze_until": inc.snooze_until,
        "first_failure_at": inc.first_failure_at,
        "mttd_seconds": mttd,
        "mttr_seconds": inc.duration_seconds,
        # V2-02-02 — network verdict (passes through unchanged)
        "network_verdict": inc.network_verdict,
        "network_verdict_computed_at": inc.network_verdict_computed_at,
    }
