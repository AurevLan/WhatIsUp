"""Probe registration, heartbeat, and result push endpoints."""

import json
import uuid
from datetime import UTC, datetime, timedelta

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.api.deps import (
    get_current_probe,
    get_current_user,
    invalidate_probe_auth_cache,
    require_superadmin,
)
from whatisup.core.database import get_db
from whatisup.core.limiter import limiter
from whatisup.core.security import (
    decrypt_custom_headers,
    decrypt_scenario_variables,
    generate_probe_api_key,
    hash_api_key,
)
from whatisup.models.discovery import DiscoveredService, DiscoverySource
from whatisup.models.incident import Incident
from whatisup.models.incident_diagnostic import DIAGNOSTIC_KINDS, IncidentDiagnostic
from whatisup.models.monitor import Monitor
from whatisup.models.probe import Probe
from whatisup.models.probe_group import probe_group_members, user_probe_group_access
from whatisup.models.result import CheckResult
from whatisup.models.user import User
from whatisup.schemas.discovery import DiscoverySourceForProbe
from whatisup.schemas.probe import (
    PendingDiagnostic,
    ProbeCheckResultIn,
    ProbeCreate,
    ProbeDiagnosticsIn,
    ProbeDiscoveryIn,
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
from whatisup.services.discovery import reconcile_source_push
from whatisup.services.incident import process_check_result

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/probes", tags=["probes"])


@router.get("/", response_model=list[ProbeOut])
@limiter.limit("60/minute")
async def list_probes(
    request: Request,
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
@limiter.limit("60/minute")
async def probe_stats(
    request: Request,
    _user: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> list[ProbeStatsOut]:
    """Return all probes with their 24h uptime percentage — used for dashboard map."""
    since = datetime.now(UTC) - timedelta(hours=24)

    probes = (await db.execute(select(Probe).order_by(Probe.created_at.desc()))).scalars().all()

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
        # Derived from the ORM row rather than hand-copied field by field: the
        # previous literal dict silently omitted every field added to ProbeOut
        # after it was written (version, discovery_capabilities,
        # ixp_membership, asn_updated_at). Building from the object means a new
        # probe field reaches this endpoint the day it reaches the model.
        out.append(
            ProbeStatsOut(
                **ProbeOut.model_validate(probe).model_dump(),
                uptime_24h=uptime,
                check_count_24h=total,
                health=health_map.get(probe.id),
            )
        )
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

    api_key, api_key_prefix = generate_probe_api_key()

    probe = Probe(
        name=payload.name,
        location_name=payload.location_name,
        latitude=payload.latitude,
        longitude=payload.longitude,
        network_type=payload.network_type,
        api_key_hash=hash_api_key(api_key),
        api_key_prefix=api_key_prefix,
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
    if payload.version and probe.version != payload.version:
        probe.version = payload.version

    # plan D, D-1 — write-if-present: a heartbeat that omits the field (older
    # probe) must not clear a previously-declared capability list, which a
    # bare "if payload.discovery_capabilities:" would do the moment a probe
    # legitimately reports zero capabilities. model_fields_set distinguishes
    # "field absent" from "field present and empty/null".
    if "discovery_capabilities" in payload.model_fields_set:
        probe.discovery_capabilities = payload.discovery_capabilities

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
        )
        .scalars()
        .all()
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
                decrypt_scenario_variables(m.scenario_variables) if m.scenario_variables else None
            ),
            trigger_now=trigger_map.get(str(m.id), False),
            smtp_port=m.smtp_port,
            smtp_starttls=m.smtp_starttls,
            udp_port=m.udp_port,
            domain_expiry_warn_days=m.domain_expiry_warn_days,
            custom_headers=decrypt_custom_headers(m.custom_headers),
            # Advanced HTTP assertions — without these the probe falls back to
            # the schema defaults (None/False) and the UI toggles are inert
            body_regex=m.body_regex,
            expected_headers=m.expected_headers,
            json_schema=m.json_schema,
            schema_drift_enabled=m.schema_drift_enabled,
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

    # plan D, D-1 — the heartbeat is the discovery control channel too (same
    # canal as monitors/pending_diagnostics): hand the probe its own enabled
    # sources only. This scoping is what push_discovery's `_probe_may_push`
    # relies on being true — a source never distributed to a probe cannot be
    # pushed to by it either.
    #
    # plan E, E-2 — a source may also target a `ProbeGroup` this probe
    # belongs to: `docker` fans out to every member that declares the
    # capability, `port_scan`/`dns_zone` go to the elected member only
    # (`services/discovery_election.py`).
    my_group_ids = {
        row[0]
        for row in (
            await db.execute(
                select(probe_group_members.c.probe_group_id).where(
                    probe_group_members.c.probe_id == probe.id
                )
            )
        ).all()
    }
    target_clause = DiscoverySource.probe_id == probe.id
    if my_group_ids:
        target_clause = or_(target_clause, DiscoverySource.probe_group_id.in_(my_group_ids))
    candidate_sources = (
        (
            await db.execute(
                select(DiscoverySource).where(target_clause, DiscoverySource.enabled.is_(True))
            )
        )
        .scalars()
        .all()
    )

    probe_capabilities = set(probe.discovery_capabilities or [])

    def _group_source_served(s: DiscoverySource) -> bool:
        if s.source_type == "docker":
            return "docker" in probe_capabilities
        return s.elected_probe_id == probe.id

    discovery_sources = [
        s for s in candidate_sources if s.probe_id == probe.id or _group_source_served(s)
    ]
    # plan E, E-1 — "scan now": same trigger-key mechanism as monitors above
    # (whatisup:trigger_check:{monitor_id}), scoped to discovery sources.
    discovery_trigger_keys = await redis.mget(
        [f"whatisup:discovery_trigger:{s.id}" for s in discovery_sources]
    )
    discovery_trigger_map = {
        str(s.id): bool(v) for s, v in zip(discovery_sources, discovery_trigger_keys)
    }
    discovery_keys_to_delete = [
        f"whatisup:discovery_trigger:{s.id}"
        for s, v in zip(discovery_sources, discovery_trigger_keys)
        if v
    ]
    if discovery_keys_to_delete:
        await redis.delete(*discovery_keys_to_delete)

    discovery_out = [
        DiscoverySourceForProbe(
            id=s.id,
            source_type=s.source_type,
            params=s.params,
            trigger_now=discovery_trigger_map.get(str(s.id), False),
        )
        for s in discovery_sources
    ]

    return ProbeHeartbeatResponse(
        monitors=configs, pending_diagnostics=pending, discovery_sources=discovery_out
    )


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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incident not found")

    # SEC-M5: a probe may only attach diagnostics to incidents whose monitor it
    # actually serves. Without this tie any authenticated probe could inject
    # forged diagnostics into arbitrary incidents (cross-probe integrity).
    serves_monitor = (
        await db.execute(
            select(CheckResult.id)
            .where(
                CheckResult.monitor_id == incident.monitor_id,
                CheckResult.probe_id == probe.id,
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if serves_monitor is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Probe does not serve this incident's monitor",
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


#: Defense in depth on `hints` even though the probe already filters/bounds
#: it before transport (plan_discovery.md § Sécurité) — mirrors how the probe
#: caps Docker labels at 16 entries / 128 chars, just at the server boundary.
_DISCOVERY_HINTS_MAX_KEYS = 32
_DISCOVERY_HINTS_KEY_MAX_LEN = 128
_DISCOVERY_HINTS_VALUE_MAX_LEN = 256
#: Non-string values (the docker source's `labels` dict) can't be truncated
#: without corrupting them — instead any value whose JSON form exceeds this
#: is dropped outright. Sized to fit a legitimate probe-side labels blob
#: (16 entries × 128+128 chars ≈ 4.5 KB) with headroom, nothing more.
_DISCOVERY_HINTS_NESTED_MAX_LEN = 8192


def _sanitize_hints(hints: dict) -> dict:
    """Truncate an oversized/oversized-value hints blob before it hits the DB."""
    out: dict = {}
    for key, value in hints.items():
        if len(out) >= _DISCOVERY_HINTS_MAX_KEYS:
            break
        if isinstance(value, str):
            if len(value) > _DISCOVERY_HINTS_VALUE_MAX_LEN:
                value = value[:_DISCOVERY_HINTS_VALUE_MAX_LEN]
        elif len(json.dumps(value)) > _DISCOVERY_HINTS_NESTED_MAX_LEN:
            continue
        out[str(key)[:_DISCOVERY_HINTS_KEY_MAX_LEN]] = value
    return out


def _normalize_discovery_target(proto: str, host: str, port: int | None) -> tuple[str, str]:
    """Compute ``(host, normalized_target)`` — never trust a canonical form
    from the probe (plan_discovery.md: "calculé côté serveur")."""
    host = host.strip().lower()
    proto = proto.strip().lower()
    target = f"{proto}://{host}:{port}" if port is not None else f"{proto}://{host}"
    return host, target


async def _probe_may_push(db: AsyncSession, source: DiscoverySource, probe: Probe) -> bool:
    """Is *probe* a legitimate runner of *source* (plan E, E-2)?

    Mirrors the heartbeat's own distribution rule exactly — a probe must
    never be able to push to a source the heartbeat would not have handed it
    in the first place. Probe-targeted: the same probe. Group-targeted: the
    probe must be a member AND (docker: declares the capability;
    port_scan/dns_zone: is the elected runner). No branch here reveals which
    check failed to the caller — see ``push_discovery``'s docstring on the
    no-oracle property this preserves.
    """
    if source.probe_id is not None:
        return source.probe_id == probe.id
    if source.probe_group_id is None:
        return False  # unreachable given ck_discovery_sources_probe_xor_group
    is_member = (
        await db.execute(
            select(probe_group_members.c.probe_id).where(
                probe_group_members.c.probe_group_id == source.probe_group_id,
                probe_group_members.c.probe_id == probe.id,
            )
        )
    ).scalar_one_or_none() is not None
    if not is_member:
        return False
    if source.source_type == "docker":
        return "docker" in (probe.discovery_capabilities or [])
    return source.elected_probe_id == probe.id


@router.post("/discovery", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit("60/minute")
async def push_discovery(
    request: Request,
    payload: ProbeDiscoveryIn,
    probe: Probe = Depends(get_current_probe),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Receive a discovery snapshot for one source (plan D, D-1).

    Storage only — this stores the snapshot as-is; reconciliation into
    reviewable state transitions (``proposed``/``orphaned``) is D-2.

    Scope-binding mirrors the v1.15 H1/H2 result rejection: a source that
    does not exist, is disabled, or belongs to a different probe than the
    one authenticated here gets the *exact same* response as a genuine
    accept (202, ``{"accepted": 0}``) — this endpoint carries no oracle that
    would let a compromised probe key learn whether a given source id
    exists, is enabled, or belongs to someone else.
    """
    source = (
        await db.execute(select(DiscoverySource).where(DiscoverySource.id == payload.source_id))
    ).scalar_one_or_none()

    if source is None or not source.enabled or not await _probe_may_push(db, source, probe):
        logger.warning(
            "discovery_push_scope_rejected",
            probe_id=str(probe.id),
            source_id=str(payload.source_id),
        )
        return {"accepted": 0}

    now = datetime.now(UTC)
    seen_targets: set[str] = set()
    # Dedup pass first, in memory — two entries normalizing to the same
    # target ("HOST" vs "host") would otherwise both insert and trip
    # uq_discovered_services_source_target at commit — a malformed snapshot
    # must not turn into a 500. Keeps only the first occurrence, same as the
    # previous per-row loop.
    to_upsert: dict[str, tuple[str, int | None, str, dict]] = {}
    for svc in payload.services:
        host, target = _normalize_discovery_target(svc.proto, svc.host, svc.port)
        if target in seen_targets:
            continue
        seen_targets.add(target)
        proto = svc.proto.strip().lower()
        hints = _sanitize_hints(svc.hints)
        to_upsert[target] = (host, svc.port, proto, hints)

    # One grouped SELECT for the whole snapshot instead of one per service
    # (mirrors the `.in_(seen_targets)` batching already used by the
    # reconciliation helpers in services/discovery.py, and for the same
    # reason: up to 500 services per push, one push per scan cycle per probe).
    existing_by_target: dict[str, DiscoveredService] = {}
    if seen_targets:
        existing_rows = (
            (
                await db.execute(
                    select(DiscoveredService).where(
                        DiscoveredService.source_id == source.id,
                        DiscoveredService.normalized_target.in_(seen_targets),
                    )
                )
            )
            .scalars()
            .all()
        )
        existing_by_target = {row.normalized_target: row for row in existing_rows}

    for target, (host, port, proto, hints) in to_upsert.items():
        existing = existing_by_target.get(target)
        if existing is None:
            db.add(
                DiscoveredService(
                    source_id=source.id,
                    host=host,
                    port=port,
                    proto=proto,
                    normalized_target=target,
                    hints=hints,
                    status="proposed",
                    first_seen_at=now,
                    last_seen_at=now,
                    status_changed_at=now,
                )
            )
        else:
            # Snapshot refresh only — `status` is never touched here. A
            # `dismissed` proposal must stay dismissed on re-push, and
            # `orphaned`/`accepted` are the reconciler's (D-2) business, not
            # this ingestion endpoint's.
            existing.last_seen_at = now
            existing.hints = hints

    accepted = len(to_upsert)

    # plan D, D-2 — turn this snapshot into reviewable state: match new
    # proposals against the owner's existing monitors, orphan/drop what's
    # missing, reactivate what reappeared. Same transaction as the upsert
    # loop above, still before commit.
    await reconcile_source_push(db, source, seen_targets, now)

    # plan E, E-1 — set unconditionally, including a snapshot with zero
    # services: "nothing found" must update `last_scan_at` exactly like a
    # snapshot full of services, otherwise it stays indistinguishable from
    # "never scanned" (piège n°1 du lot).
    source.last_scan_at = now
    source.last_scan_target_count = accepted
    source.last_scan_probe_id = probe.id

    await db.commit()
    return {"accepted": accepted}


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

    # H2 — bind the authenticated probe to the monitor it reports on.
    # The heartbeat only hands a monitor's config to probes whose network_type
    # matches the monitor's network_scope (or scope "all"), AND never distributes
    # composite monitors (which have no physical check) at all — those two
    # filters are the sole probe↔monitor "assignment" the system models. A result
    # for a monitor outside that scope, or for a composite monitor, means a
    # compromised/misused key is forging data for an arbitrary monitor → reject.
    # Scope "all" stays served by every probe, so unassigned monitors keep their
    # permissive default. This check is O(1) on already-loaded rows — no extra
    # DB/Redis round-trip on the hot path.
    if monitor.check_type == "composite" or (
        monitor.network_scope != "all" and monitor.network_scope != probe.network_type
    ):
        logger.warning(
            "probe_result_scope_rejected",
            probe_id=str(probe.id),
            monitor_id=str(monitor.id),
            monitor_scope=monitor.network_scope,
            probe_network_type=str(probe.network_type),
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Probe network scope does not serve this monitor",
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
        from whatisup.services import health as health_service

        async with get_session_factory()() as bg_db:
            bg_result = (await bg_db.execute(select(CR).where(CR.id == result_id))).scalar_one()
            await process_check_result(bg_db, bg_result, manager.broadcast)
            try:
                # publish_event passed → ingest evaluates SLO rules and may
                # drive incidents on monitors with health_engine_enabled=True.
                # Failure must never break the legacy pipeline.
                await health_service.ingest(bg_db, bg_result, publish_event=manager.broadcast)
            except Exception as exc:
                logger.warning(
                    "health_ingest_failed",
                    monitor_id=str(bg_result.monitor_id),
                    error=str(exc),
                )
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
    user: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> Probe:
    probe = (await db.execute(select(Probe).where(Probe.id == probe_id))).scalar_one_or_none()
    if probe is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Probe not found")
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(probe, field, value)
    # NOTE (R-01): If is_active is being set to False, the Redis probe-auth cache entry for
    # this probe's API key cannot be invalidated precisely (we don't hold the raw key here).
    # The stale entry will be rejected on the next fast-path hit (probe not found / inactive)
    # and evicted automatically. The maximum stale window is the cache TTL (60 seconds).
    await db.flush()
    from whatisup.services.audit import log_action

    # ProbeUpdate (location_name/latitude/longitude/is_active/network_type) carries no
    # Fernet-encrypted secret — safe to log verbatim as the diff.
    await log_action(db, "probe.update", "probe", probe.id, probe.name, user, diff=changes)
    logger.info("probe_updated", probe_id=str(probe.id))
    return probe


@router.delete("/{probe_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("30/minute")
async def delete_probe(
    request: Request,
    probe_id: uuid.UUID,
    user: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> None:
    probe = (await db.execute(select(Probe).where(Probe.id == probe_id))).scalar_one_or_none()
    if probe is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Probe not found")
    from whatisup.services.audit import log_action

    await log_action(db, "probe.delete", "probe", probe.id, probe.name, user)
    await db.delete(probe)
    # NOTE (R-01): The Redis probe-auth cache entry for this probe's API key cannot be
    # invalidated here (we don't hold the raw key). On the next fast-path hit the DB lookup
    # will return None and the stale cache entry will be evicted. The maximum stale window
    # is the cache TTL (60 seconds).
    logger.info("probe_deleted", probe_id=str(probe_id))


@router.post("/{probe_id}/rotate-key", response_model=ProbeRegistered)
@limiter.limit("10/minute")
async def rotate_probe_key(
    request: Request,
    probe_id: uuid.UUID,
    user: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Rotate a probe's API key (H1).

    Superadmin-only. Generates a fresh key, stores its bcrypt hash, and returns
    the plaintext key **once** — it is never retrievable afterwards. The previous
    key is invalidated immediately: its hash is overwritten AND the Redis
    probe-auth cache entry is evicted, so the old key cannot keep authenticating
    on the fast path during the cache TTL window. The probe must be re-enrolled
    with the new key.
    """
    probe = (await db.execute(select(Probe).where(Probe.id == probe_id))).scalar_one_or_none()
    if probe is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Probe not found")

    api_key, api_key_prefix = generate_probe_api_key()
    probe.api_key_hash = hash_api_key(api_key)
    # Populate the public prefix so this probe leaves the legacy scan set and
    # authenticates via the fast indexed lookup from now on (migration path).
    probe.api_key_prefix = api_key_prefix

    from whatisup.services.audit import log_action

    await log_action(db, "probe.rotate_key", "probe", probe.id, probe.name, user)

    # Commit the new hash BEFORE evicting the cache. Evicting first would open a
    # race: a concurrent request presenting the OLD key cache-misses between the
    # eviction and the (deferred) commit, runs the bcrypt slow path on a session
    # that still sees the OLD committed hash, re-authenticates and re-populates
    # the forward cache + reverse index for another TTL window — keeping the
    # compromised key valid up to ~60 s after rotation. Committing first means
    # any slow-path scan can only ever match the NEW hash. Defense in depth (SA6):
    # deps.get_current_probe additionally fingerprints cache values with the bcrypt
    # hash and guards slow-path cache writes, so even a bcrypt verification already
    # in flight against the OLD hash cannot re-cache the old key.
    await db.commit()

    # Best-effort eviction: the new key is already durably committed, so if Redis
    # is momentarily unavailable the stale forward entry simply expires on its own
    # within the cache TTL (≤60 s). Never fail the rotation (and lose the freshly
    # minted key, shown only once) over a cache op.
    try:
        await invalidate_probe_auth_cache(probe.id)
    except Exception as exc:
        logger.warning("probe_auth_cache_evict_failed", probe_id=str(probe.id), error=str(exc))

    logger.info("probe_key_rotated", probe_id=str(probe.id))

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
        row for row in all_incidents if probe_id_str in (row.Incident.affected_probe_ids or [])
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
