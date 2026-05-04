"""Probe registration, heartbeat, and result push endpoints."""

import uuid
from datetime import UTC, datetime, timedelta

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.api.deps import get_current_probe, get_current_user, require_superadmin
from whatisup.core.database import get_db
from whatisup.core.limiter import limiter
from whatisup.core.security import (
    decrypt_scenario_variables,
    generate_probe_api_key,
    hash_api_key,
)
from whatisup.models.incident import Incident
from whatisup.models.incident_diagnostic import DIAGNOSTIC_KINDS, IncidentDiagnostic
from whatisup.models.monitor import Monitor
from whatisup.models.probe import Probe
from whatisup.models.probe_group import probe_group_members, user_probe_group_access
from whatisup.models.result import CheckResult
from whatisup.models.user import User
from whatisup.schemas.probe import (
    PendingDiagnostic,
    ProbeCheckResultIn,
    ProbeCreate,
    ProbeDiagnosticsIn,
    ProbeHealthPayload,
    ProbeHeartbeatRequest,
    ProbeHeartbeatResponse,
    ProbeMonitorConfig,
    ProbeOut,
    ProbeRegistered,
    ProbeStatsOut,
    ProbeUpdate,
)
from whatisup.services.diagnostics import drain_pending_diagnostics
from whatisup.services.incident import process_check_result

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/probes", tags=["probes"])


@router.get("/", response_model=list[ProbeOut])
async def list_probes(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[Probe]:
    if current_user.is_superadmin:
        result = await db.execute(select(Probe).order_by(Probe.created_at.desc()))
        return list(result.scalars().all())
    # Regular user: only probes in accessible groups
    stmt = (
        select(Probe)
        .join(probe_group_members, Probe.id == probe_group_members.c.probe_id)
        .join(
            user_probe_group_access,
            probe_group_members.c.probe_group_id == user_probe_group_access.c.probe_group_id,
        )
        .where(user_probe_group_access.c.user_id == current_user.id)
        .distinct()
        .order_by(Probe.created_at.desc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get("/stats", response_model=list[ProbeStatsOut])
async def probe_stats(
    _user: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Return all probes with their 24h uptime percentage — used for dashboard map."""
    since = datetime.now(UTC) - timedelta(hours=24)

    probes = (
        await db.execute(select(Probe).order_by(Probe.created_at.desc()))
    ).scalars().all()

    # Single aggregation query: up checks / total checks per probe in last 24h
    agg = (
        await db.execute(
            select(
                CheckResult.probe_id,
                func.count().label("total"),
                func.sum(case((CheckResult.status == "up", 1), else_=0)).label("up_count"),
            )
            .where(CheckResult.checked_at >= since)
            .group_by(CheckResult.probe_id)
        )
    ).all()

    stats_map = {row.probe_id: row for row in agg}

    # Fetch live health metrics from Redis (written at each heartbeat, TTL 120s)
    from whatisup.core.redis import get_redis

    redis = get_redis()
    health_values = await redis.mget([f"whatisup:probe_health:{p.id}" for p in probes])
    health_map: dict[uuid.UUID, ProbeHealthPayload] = {}
    for probe, hv in zip(probes, health_values):
        if hv:
            try:
                health_map[probe.id] = ProbeHealthPayload.model_validate_json(hv)
            except Exception:
                logger.warning("probe_health_parse_failed", probe_id=str(probe.id))

    out = []
    for probe in probes:
        row = stats_map.get(probe.id)
        total = int(row.total) if row else 0
        up = int(row.up_count) if row else 0
        uptime = round(up / total * 100, 2) if total > 0 else None
        out.append({
            "id": probe.id,
            "name": probe.name,
            "location_name": probe.location_name,
            "latitude": probe.latitude,
            "longitude": probe.longitude,
            "is_active": probe.is_active,
            "last_seen_at": probe.last_seen_at,
            "network_type": probe.network_type,
            "uptime_24h": uptime,
            "check_count_24h": total,
            "health": health_map.get(probe.id),
            # V2-02-06 + V2-02-07 — surface ASN + outbound IP info to the map.
            "public_ip": probe.public_ip,
            "asn": probe.asn,
            "asn_name": probe.asn_name,
            "self_reported_ip": probe.self_reported_ip,
            "self_reported_asn": probe.self_reported_asn,
        })
    return out


@router.post("/register", response_model=ProbeRegistered, status_code=status.HTTP_201_CREATED)
async def register_probe(
    payload: ProbeCreate,
    _user: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    existing = (
        await db.execute(select(Probe).where(Probe.name == payload.name))
    ).scalar_one_or_none()
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


@router.post("/heartbeat", response_model=ProbeHeartbeatResponse)
@limiter.limit("120/minute")
async def heartbeat(
    request: Request,
    payload: ProbeHeartbeatRequest,
    probe: Probe = Depends(get_current_probe),
    db: AsyncSession = Depends(get_db),
) -> ProbeHeartbeatResponse:
    """Probe heartbeat — updates last_seen, stores health metrics, returns monitor list."""
    probe.last_seen_at = datetime.now(UTC)

    # V2-02-01 / V2-02-07 — opportunistic ASN enrichment.
    # Resolves the ASN of (a) the IP the server sees on the heartbeat
    # connection AND (b) the IP the probe self-reported via api.ipify.org.
    # Best-effort, never raises.
    from whatisup.services.probe_enrichment import maybe_enrich_on_heartbeat

    client_host = request.client.host if request.client else None
    await maybe_enrich_on_heartbeat(db, probe, client_host, payload.self_reported_ip)

    from whatisup.core.redis import get_redis

    redis = get_redis()

    if payload.health:
        await redis.set(
            f"whatisup:probe_health:{probe.id}",
            payload.health.model_dump_json(),
            ex=120,
        )

    monitors = list(
        (
            await db.execute(
                select(Monitor).where(
                    Monitor.enabled.is_(True),
                    Monitor.check_type != "composite",  # composite monitors have no physical check
                    or_(
                        Monitor.network_scope == "all",
                        Monitor.network_scope == probe.network_type,
                    ),
                )
            )
        ).scalars().all()
    )

    # Check for immediate trigger requests set via the trigger-check endpoint
    trigger_keys = await redis.mget([f"whatisup:trigger_check:{m.id}" for m in monitors])
    trigger_map = {str(m.id): bool(v) for m, v in zip(monitors, trigger_keys)}

    # Consume (delete) the trigger keys that were set
    keys_to_delete = [f"whatisup:trigger_check:{m.id}" for m, v in zip(monitors, trigger_keys) if v]
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
            ssl_pin_sha256=m.ssl_pin_sha256,
            ssl_min_chain_days=m.ssl_min_chain_days,
            check_type=m.check_type,
            tcp_port=m.tcp_port,
            dns_record_type=m.dns_record_type,
            dns_expected_value=m.dns_expected_value,
            dns_nameservers=m.dns_nameservers,
            keyword=m.keyword,
            keyword_negate=m.keyword_negate,
            expected_json_path=m.expected_json_path,
            expected_json_value=m.expected_json_value,
            scenario_steps=m.scenario_steps,
            scenario_variables=(
                decrypt_scenario_variables(m.scenario_variables)
                if m.scenario_variables
                else None
            ),
            trigger_now=trigger_map.get(str(m.id), False),
            smtp_port=m.smtp_port,
            smtp_starttls=m.smtp_starttls,
            udp_port=m.udp_port,
            domain_expiry_warn_days=m.domain_expiry_warn_days,
            custom_headers=m.custom_headers,
        )
        for m in monitors
    ]

    # V2-01-01 — drain pending diagnostic requests for this probe
    pending_specs = await drain_pending_diagnostics(probe.id)
    pending = [
        PendingDiagnostic(
            incident_id=spec["incident_id"],
            monitor_id=spec["monitor_id"],
            target=spec["target"],
            check_type=spec.get("check_type", "http"),
            kinds=spec.get("kinds", list(DIAGNOSTIC_KINDS)),
        )
        for spec in pending_specs
    ]

    return ProbeHeartbeatResponse(monitors=configs, pending_diagnostics=pending)


@router.post("/diagnostics", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit("60/minute")
async def push_diagnostics(
    request: Request,
    payload: ProbeDiagnosticsIn,
    probe: Probe = Depends(get_current_probe),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Receive a batch of diagnostic results collected by the probe (V2-01-01)."""
    incident = (
        await db.execute(select(Incident).where(Incident.id == payload.incident_id))
    ).scalar_one_or_none()
    if incident is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Incident not found"
        )

    valid_kinds = set(DIAGNOSTIC_KINDS)
    inserted = 0
    for r in payload.results:
        if r.kind not in valid_kinds:
            # Silently skip unknown kinds — keep the rest of the batch usable.
            continue
        diag = IncidentDiagnostic(
            incident_id=incident.id,
            probe_id=probe.id,
            kind=r.kind,
            payload=r.payload,
            error=r.error,
            collected_at=r.collected_at,
        )
        db.add(diag)
        inserted += 1
    await db.commit()
    return {"accepted": inserted}


@router.post("/results", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit("600/minute")
async def push_result(
    request: Request,
    payload: ProbeCheckResultIn,
    background_tasks: BackgroundTasks,
    probe: Probe = Depends(get_current_probe),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Receive a check result from a probe and trigger incident detection."""
    monitor = (
        await db.execute(
            select(Monitor).where(Monitor.id == payload.monitor_id, Monitor.enabled.is_(True))
        )
    ).scalar_one_or_none()
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
        dns_resolved_values=payload.dns_resolved_values,
        dns_resolve_ms=payload.dns_resolve_ms,
        ttfb_ms=payload.ttfb_ms,
        download_ms=payload.download_ms,
        schema_fingerprint=payload.schema_fingerprint,
        tls_audit=payload.tls_audit,
        dns_consistency=payload.dns_consistency,
    )
    db.add(result)
    probe.last_seen_at = datetime.now(UTC)
    await db.flush()

    # DNS semantic checks (drift + cross-probe consistency) — modifies result in-place if needed
    from whatisup.services.dns import apply_dns_semantic_check

    await apply_dns_semantic_check(db, monitor, result)

    result_id = result.id
    await db.commit()  # commit before background task so the result is visible in a new session

    from whatisup.api.v1.ws import manager

    async def _process():
        from whatisup.core.database import get_session_factory
        from whatisup.models.result import CheckResult as CR

        async with get_session_factory()() as bg_db:
            bg_result = (await bg_db.execute(select(CR).where(CR.id == result_id))).scalar_one()
            await process_check_result(bg_db, bg_result, manager.broadcast)
            await bg_db.commit()

    background_tasks.add_task(_process)
    return {"accepted": True}


@router.get("/{probe_id}", response_model=ProbeOut)
@limiter.limit("30/minute")
async def get_probe(
    request: Request,
    probe_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_superadmin),
) -> Probe:
    target = (await db.execute(select(Probe).where(Probe.id == probe_id))).scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Probe not found")
    return target


@router.patch("/{probe_id}", response_model=ProbeOut)
@limiter.limit("30/minute")
async def update_probe(
    request: Request,
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
@limiter.limit("30/minute")
async def delete_probe(
    request: Request,
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


@router.get("/{probe_id}/incident-timeline")
@limiter.limit("30/minute")
async def get_probe_incident_timeline(
    request: Request,
    probe_id: uuid.UUID,
    days: int = Query(default=7, ge=1, le=90),
    _user: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Timeline of all monitors put into incident by this probe within the last N days.

    Returns a list of monitors with their incidents during the window, sorted
    by most recent incident first — useful for diagnosing network-localized outages.
    """
    from whatisup.models.incident import Incident
    from whatisup.models.monitor import Monitor

    probe = (await db.execute(select(Probe).where(Probe.id == probe_id))).scalar_one_or_none()
    if probe is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Probe not found")

    cutoff = datetime.now(UTC) - timedelta(days=days)

    # Find all incidents that had this probe in their affected_probe_ids
    # (JSON contains check via LIKE is approximate but works for UUID strings)
    probe_id_str = str(probe_id)
    all_incidents = (
        await db.execute(
            select(Incident, Monitor.name, Monitor.url, Monitor.check_type)
            .join(Monitor, Incident.monitor_id == Monitor.id)
            .where(Incident.started_at >= cutoff)
            .order_by(Incident.started_at.desc())
        )
    ).all()

    # Filter in Python for probe membership (JSON array contains probe_id)
    relevant = [
        row for row in all_incidents
        if probe_id_str in (row.Incident.affected_probe_ids or [])
    ]

    # Group by monitor
    monitors_map: dict[str, dict] = {}
    for row in relevant:
        inc = row.Incident
        mid = str(inc.monitor_id)
        if mid not in monitors_map:
            monitors_map[mid] = {
                "monitor_id": mid,
                "monitor_name": row.name,
                "monitor_url": row.url,
                "check_type": row.check_type,
                "incidents": [],
            }
        monitors_map[mid]["incidents"].append(
            {
                "id": str(inc.id),
                "started_at": inc.started_at.isoformat(),
                "resolved_at": inc.resolved_at.isoformat() if inc.resolved_at else None,
                "duration_seconds": inc.duration_seconds,
                "scope": inc.scope.value,
            }
        )

    # Sort monitors by most recent incident
    result = sorted(
        monitors_map.values(),
        key=lambda m: m["incidents"][0]["started_at"] if m["incidents"] else "",
        reverse=True,
    )
    return result
