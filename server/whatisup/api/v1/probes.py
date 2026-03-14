"""Probe registration, heartbeat, and result push endpoints."""

import uuid
from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.api.deps import get_current_probe, get_current_user, require_superadmin
from whatisup.core.database import get_db
from whatisup.core.limiter import limiter
from whatisup.core.security import generate_probe_api_key, hash_api_key
from whatisup.models.monitor import Monitor
from whatisup.models.probe import Probe
from whatisup.models.result import CheckResult
from whatisup.models.user import User
from whatisup.schemas.probe import (
    ProbeCheckResultIn,
    ProbeCreate,
    ProbeHeartbeatResponse,
    ProbeMonitorConfig,
    ProbeOut,
    ProbeRegistered,
    ProbeUpdate,
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
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Probe name already exists"
        )

    api_key = generate_probe_api_key()

    probe = Probe(
        name=payload.name,
        location_name=payload.location_name,
        latitude=payload.latitude,
        longitude=payload.longitude,
        network_type=payload.network_type,
        api_key_hash=hash_api_key(api_key),
    )
    db.add(probe)
    await db.flush()

    logger.info("probe_registered", probe_id=str(probe.id), name=probe.name)

    from whatisup.services.audit import log_action
    await log_action(db, "probe.register", "probe", probe.id, probe.name, None)

    return {
        "id": probe.id,
        "name": probe.name,
        "location_name": probe.location_name,
        "latitude": probe.latitude,
        "longitude": probe.longitude,
        "is_active": probe.is_active,
        "last_seen_at": probe.last_seen_at,
        "network_type": probe.network_type,
        "api_key": api_key,
    }


@router.get("/heartbeat", response_model=ProbeHeartbeatResponse)
@limiter.limit("30/minute")
async def heartbeat(
    request: Request,
    probe: Probe = Depends(get_current_probe),
    db: AsyncSession = Depends(get_db),
) -> ProbeHeartbeatResponse:
    """Probe heartbeat — returns current list of enabled monitors to check."""
    probe.last_seen_at = datetime.now(UTC)

    monitors = list((await db.execute(
        select(Monitor).where(Monitor.enabled.is_(True))
    )).scalars().all())

    # Check for immediate trigger requests set via the trigger-check endpoint
    from whatisup.core.redis import get_redis
    redis = get_redis()
    trigger_keys = await redis.mget([f"whatisup:trigger_check:{m.id}" for m in monitors])
    trigger_map = {str(m.id): bool(v) for m, v in zip(monitors, trigger_keys)}

    # Consume (delete) the trigger keys that were set
    keys_to_delete = [
        f"whatisup:trigger_check:{m.id}"
        for m, v in zip(monitors, trigger_keys)
        if v
    ]
    if keys_to_delete:
        await redis.delete(*keys_to_delete)

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
            check_type=m.check_type,
            tcp_port=m.tcp_port,
            dns_record_type=m.dns_record_type,
            dns_expected_value=m.dns_expected_value,
            keyword=m.keyword,
            keyword_negate=m.keyword_negate,
            expected_json_path=m.expected_json_path,
            expected_json_value=m.expected_json_value,
            scenario_steps=m.scenario_steps,
            scenario_variables=m.scenario_variables,
            trigger_now=trigger_map.get(str(m.id), False),
        )
        for m in monitors
    ]
    return ProbeHeartbeatResponse(monitors=configs)


@router.post("/results", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit("60/minute")
async def push_result(
    request: Request,
    payload: ProbeCheckResultIn,
    background_tasks: BackgroundTasks,
    probe: Probe = Depends(get_current_probe),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Receive a check result from a probe and trigger incident detection."""
    monitor = (await db.execute(
        select(Monitor).where(Monitor.id == payload.monitor_id, Monitor.enabled.is_(True))
    )).scalar_one_or_none()
    if monitor is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Monitor not found or disabled"
        )

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
        scenario_result=payload.scenario_result,
    )
    db.add(result)
    probe.last_seen_at = datetime.now(UTC)
    await db.flush()
    result_id = result.id
    await db.commit()  # commit before background task so the result is visible in a new session

    from whatisup.api.v1.ws import manager

    async def _process():
        from whatisup.core.database import get_session_factory
        from whatisup.models.result import CheckResult as CR
        async with get_session_factory()() as bg_db:
            bg_result = (await bg_db.execute(
                select(CR).where(CR.id == result_id)
            )).scalar_one()
            await process_check_result(bg_db, bg_result, manager.broadcast)
            await bg_db.commit()

    background_tasks.add_task(_process)
    return {"accepted": True}


@router.get("/{probe_id}", response_model=ProbeOut)
async def get_probe(
    probe_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_superadmin),
) -> Probe:
    target = (await db.execute(select(Probe).where(Probe.id == probe_id))).scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Probe not found")
    return target


@router.patch("/{probe_id}", response_model=ProbeOut)
async def update_probe(
    probe_id: uuid.UUID,
    payload: ProbeUpdate,
    _user: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> Probe:
    probe = (await db.execute(select(Probe).where(Probe.id == probe_id))).scalar_one_or_none()
    if probe is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Probe not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(probe, field, value)
    # NOTE (R-01): If is_active is being set to False, the Redis probe-auth cache entry for
    # this probe's API key cannot be invalidated precisely (we don't hold the raw key here).
    # The stale entry will be rejected on the next fast-path hit (probe not found / inactive)
    # and evicted automatically. The maximum stale window is the cache TTL (300 seconds).
    await db.flush()
    logger.info("probe_updated", probe_id=str(probe.id))
    return probe


@router.delete("/{probe_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_probe(
    probe_id: uuid.UUID,
    _user: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> None:
    probe = (await db.execute(select(Probe).where(Probe.id == probe_id))).scalar_one_or_none()
    if probe is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Probe not found")
    from whatisup.services.audit import log_action
    await log_action(db, "probe.delete", "probe", probe.id, probe.name, None)
    await db.delete(probe)
    # NOTE (R-01): The Redis probe-auth cache entry for this probe's API key cannot be
    # invalidated here (we don't hold the raw key). On the next fast-path hit the DB lookup
    # will return None and the stale cache entry will be evicted. The maximum stale window
    # is the cache TTL (300 seconds).
    logger.info("probe_deleted", probe_id=str(probe_id))


