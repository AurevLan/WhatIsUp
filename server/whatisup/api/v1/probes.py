"""Probe registration, heartbeat, and result push endpoints."""

import uuid
from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.api.deps import get_current_probe, require_superadmin
from whatisup.core.database import get_db
from whatisup.core.security import generate_probe_api_key, hash_api_key
from whatisup.models.monitor import Monitor
from whatisup.models.probe import Probe
from whatisup.models.result import CheckResult
from whatisup.models.user import User
from whatisup.schemas.probe import (
    ProbeCreate,
    ProbeHeartbeatResponse,
    ProbeMonitorConfig,
    ProbeOut,
    ProbeRegistered,
    ProbeCheckResultIn,
)
from whatisup.services.incident import process_check_result

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/probes", tags=["probes"])


@router.get("/", response_model=list[ProbeOut])
async def list_probes(
    _user: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> list[Probe]:
    result = await db.execute(select(Probe).order_by(Probe.created_at.desc()))
    return list(result.scalars().all())


@router.post("/register", response_model=ProbeRegistered, status_code=status.HTTP_201_CREATED)
async def register_probe(
    payload: ProbeCreate,
    _user: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    existing = (await db.execute(
        select(Probe).where(Probe.name == payload.name)
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Probe name already exists")

    api_key = generate_probe_api_key()

    probe = Probe(
        name=payload.name,
        location_name=payload.location_name,
        latitude=payload.latitude,
        longitude=payload.longitude,
        api_key_hash=hash_api_key(api_key),
    )
    db.add(probe)
    await db.flush()

    logger.info("probe_registered", probe_id=str(probe.id), name=probe.name)

    return {
        "id": probe.id,
        "name": probe.name,
        "location_name": probe.location_name,
        "latitude": probe.latitude,
        "longitude": probe.longitude,
        "is_active": probe.is_active,
        "last_seen_at": probe.last_seen_at,
        "api_key": api_key,
    }


@router.get("/heartbeat", response_model=ProbeHeartbeatResponse)
async def heartbeat(
    probe: Probe = Depends(get_current_probe),
    db: AsyncSession = Depends(get_db),
) -> ProbeHeartbeatResponse:
    """Probe heartbeat — returns current list of enabled monitors to check."""
    probe.last_seen_at = datetime.now(UTC)

    monitors = (await db.execute(
        select(Monitor).where(Monitor.enabled == True)
    )).scalars().all()

    configs = [
        ProbeMonitorConfig(
            id=m.id,
            url=m.url,
            interval_seconds=m.interval_seconds,
            timeout_seconds=m.timeout_seconds,
            follow_redirects=m.follow_redirects,
            expected_status_codes=m.expected_status_codes,
            ssl_check_enabled=m.ssl_check_enabled,
            ssl_expiry_warn_days=m.ssl_expiry_warn_days,
        )
        for m in monitors
    ]
    return ProbeHeartbeatResponse(monitors=configs)


@router.post("/results", status_code=status.HTTP_202_ACCEPTED)
async def push_result(
    payload: ProbeCheckResultIn,
    background_tasks: BackgroundTasks,
    probe: Probe = Depends(get_current_probe),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Receive a check result from a probe and trigger incident detection."""
    monitor = (await db.execute(
        select(Monitor).where(Monitor.id == payload.monitor_id, Monitor.enabled == True)
    )).scalar_one_or_none()
    if monitor is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Monitor not found or disabled")

    result = CheckResult(
        monitor_id=payload.monitor_id,
        probe_id=probe.id,
        checked_at=payload.checked_at,
        status=payload.status,
        http_status=payload.http_status,
        response_time_ms=payload.response_time_ms,
        redirect_count=payload.redirect_count,
        final_url=payload.final_url,
        ssl_valid=payload.ssl_valid,
        ssl_expires_at=payload.ssl_expires_at,
        ssl_days_remaining=payload.ssl_days_remaining,
        error_message=payload.error_message,
    )
    db.add(result)
    probe.last_seen_at = datetime.now(UTC)
    await db.flush()

    from whatisup.api.v1.ws import manager

    async def _process():
        from whatisup.core.database import get_session_factory
        async with get_session_factory()() as bg_db:
            await process_check_result(bg_db, result, manager.broadcast)
            await bg_db.commit()

    background_tasks.add_task(_process)
    return {"accepted": True}


@router.get("/{probe_id}", response_model=ProbeOut)
async def get_probe(
    probe_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    probe: Probe = Depends(get_current_probe),
) -> Probe:
    target = (await db.execute(select(Probe).where(Probe.id == probe_id))).scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Probe not found")
    if target.id != probe.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    return target


@router.delete("/{probe_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_probe(
    probe_id: uuid.UUID,
    _user: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> None:
    probe = (await db.execute(select(Probe).where(Probe.id == probe_id))).scalar_one_or_none()
    if probe is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Probe not found")
    probe.is_active = False


