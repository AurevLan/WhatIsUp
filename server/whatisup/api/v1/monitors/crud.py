"""Monitor CRUD endpoints — list, create, read, update, delete, bulk, trigger."""

import logging
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import and_, delete, func, select, true, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.api.deps import (
    assert_can_assign_group,
    assert_can_assign_team,
    build_access_filter,
    check_resource_access,
    get_current_user,
    get_user_team_ids,
)
from whatisup.api.v1.monitors._common import _get_monitor_or_404
from whatisup.core.database import dialect_name, get_db
from whatisup.core.limiter import limiter
from whatisup.core.security import (
    encrypt_custom_headers,
    encrypt_scenario_variables,
    generate_heartbeat_token,
)
from whatisup.models.incident import IS_AVAILABILITY_INCIDENT, Incident
from whatisup.models.monitor import Monitor, MonitorGroup, monitor_tags
from whatisup.models.result import CheckResult
from whatisup.models.tag import Tag
from whatisup.models.team import TeamRole
from whatisup.models.user import User
from whatisup.schemas.monitor import (
    BulkActionRequest,
    BulkActionResponse,
    MonitorCreate,
    MonitorOut,
    MonitorUpdate,
)
from whatisup.services.stats import (
    compute_uptime_bulk,
    fetch_latest_results,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/monitors", tags=["monitors"])


@router.get("/", response_model=list[MonitorOut])
@limiter.limit("120/minute")
async def list_monitors(
    request: Request,
    response: Response,
    enabled: bool | None = None,
    group_id: uuid.UUID | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    query = select(Monitor)
    if not current_user.is_superadmin:
        team_ids = await get_user_team_ids(current_user, db)
        query = query.where(build_access_filter(Monitor, current_user, team_ids))
    if enabled is not None:
        query = query.where(Monitor.enabled == enabled)
    if group_id is not None:
        query = query.where(Monitor.group_id == group_id)

    # Total count before pagination
    total_count = (
        await db.execute(select(func.count()).select_from(query.subquery()))
    ).scalar_one()
    response.headers["X-Total-Count"] = str(total_count)

    monitors = list(
        (await db.execute(query.order_by(Monitor.created_at.desc()).limit(limit).offset(offset)))
        .scalars()
        .all()
    )

    if not monitors:
        return []

    monitor_ids = [m.id for m in monitors]

    # Latest status + response time per monitor — LATERAL on PostgreSQL, see
    # fetch_latest_results (a GROUP BY max(checked_at) aggregates every
    # historical row of the listed monitors, ~8 s on 5M rows — #218).
    latest_by_monitor = await fetch_latest_results(db, monitor_ids)
    # Map: monitor_id → (status_value, checked_at)
    latest_map = {str(mid): (r.status.value, r.checked_at) for mid, r in latest_by_monitor.items()}
    # Last response time per monitor (same latest row)
    rt_map = {
        str(mid): round(r.response_time_ms, 1)
        for mid, r in latest_by_monitor.items()
        if r.response_time_ms is not None
    }

    # Uptime 24h per monitor (multi-probe consensus, one query)
    cutoff = datetime.now(UTC) - timedelta(hours=24)
    uptime_bulk = await compute_uptime_bulk(db, monitor_ids, period_hours=24)
    uptime_map = {mid: data["uptime_percent"] for mid, data in uptime_bulk.items()}

    # P95 response time 24h per monitor (one query)
    # percentile_cont is PostgreSQL-only; fall back to AVG for SQLite (tests)
    if dialect_name(db) == "sqlite":
        p95_col = func.avg(CheckResult.response_time_ms).label("p95")
    else:
        p95_col = func.percentile_cont(0.95).within_group(CheckResult.response_time_ms).label("p95")
    p95_rows = (
        await db.execute(
            select(CheckResult.monitor_id, p95_col)
            .where(
                CheckResult.monitor_id.in_(monitor_ids),
                CheckResult.checked_at >= cutoff,
                CheckResult.response_time_ms.isnot(None),
            )
            .group_by(CheckResult.monitor_id)
        )
    ).all()
    p95_map = {str(r.monitor_id): round(r.p95, 1) for r in p95_rows if r.p95 is not None}

    # Sparkline: last 20 response_time_ms per monitor. A LATERAL join is orders
    # of magnitude faster than `row_number() OVER (PARTITION BY ...)` on a large
    # check_results table — the window function sorts the whole partition set
    # (seconds on millions of rows), LATERAL hits ix_check_results_monitor_checked
    # once per monitor for 20 rows (milliseconds).
    if dialect_name(db) == "sqlite":
        # SQLite LATERAL support is recent (3.45+) and not uniformly available in
        # test containers — keep the window function for SQLite only.
        sparkline_sub = (
            select(
                CheckResult.monitor_id,
                CheckResult.response_time_ms,
                func.row_number()
                .over(
                    partition_by=CheckResult.monitor_id,
                    order_by=CheckResult.checked_at.desc(),
                )
                .label("rn"),
            )
            .where(
                CheckResult.monitor_id.in_(monitor_ids),
                CheckResult.response_time_ms.isnot(None),
            )
            .subquery()
        )
        sparkline_rows = (
            await db.execute(
                select(sparkline_sub.c.monitor_id, sparkline_sub.c.response_time_ms)
                .where(sparkline_sub.c.rn <= 20)
                .order_by(sparkline_sub.c.monitor_id, sparkline_sub.c.rn.desc())
            )
        ).all()
    else:
        lateral = (
            select(CheckResult.response_time_ms, CheckResult.checked_at)
            .where(
                CheckResult.monitor_id == Monitor.id,
                CheckResult.response_time_ms.isnot(None),
            )
            .order_by(CheckResult.checked_at.desc())
            .limit(20)
            .lateral("last_rt")
        )
        sparkline_rows = (
            await db.execute(
                select(Monitor.id, lateral.c.response_time_ms, lateral.c.checked_at)
                .select_from(Monitor.__table__.join(lateral, true()))
                .where(Monitor.id.in_(monitor_ids))
                .order_by(Monitor.id, lateral.c.checked_at.desc())
            )
        ).all()
    sparkline_map: dict[str, list[float]] = {}
    for row in sparkline_rows:
        # Row shape differs between the two branches; normalize to (mid, rt).
        mid_val = row[0]
        rt = row[1]
        sparkline_map.setdefault(str(mid_val), []).append(round(rt, 1) if rt else 0)

    # plan_cap_v2 §3a — open availability incident + its network verdict, one
    # bulk query. IS_AVAILABILITY_INCIDENT excludes metric incidents (C-4):
    # those don't mean "the monitor is down" and carry no verdict anyway.
    open_incident_rows = (
        await db.execute(
            select(Incident.monitor_id, Incident.network_verdict).where(
                Incident.monitor_id.in_(monitor_ids),
                Incident.resolved_at.is_(None),
                IS_AVAILABILITY_INCIDENT,
            )
        )
    ).all()
    open_incident_map = {str(r.monitor_id): r.network_verdict for r in open_incident_rows}

    now = datetime.now(UTC)
    out = []
    for m in monitors:
        mid = str(m.id)
        d = MonitorOut.model_validate(m).model_dump()
        entry = latest_map.get(mid)
        if entry:
            status_val, checked_at = entry
            # asyncpg returns tz-aware timestamps; SQLite (tests) returns naive —
            # normalize before subtracting, matching slo.py / health.py.
            if checked_at.tzinfo is None:
                checked_at = checked_at.replace(tzinfo=UTC)
            age = (now - checked_at).total_seconds()
            threshold = max(300, m.interval_seconds * 3)
            d["last_status"] = status_val if age < threshold else None
        else:
            d["last_status"] = None
        d["uptime_24h"] = uptime_map.get(mid)
        d["last_response_time_ms"] = rt_map.get(mid)
        d["p95_response_time_ms"] = p95_map.get(mid)
        d["sparkline"] = sparkline_map.get(mid, [])
        d["has_open_incident"] = mid in open_incident_map
        d["network_verdict"] = open_incident_map.get(mid)
        out.append(d)
    return out


async def _create_monitor_from_payload(
    db: AsyncSession, current_user: User, payload: MonitorCreate
) -> Monitor:
    """Shared creation body — the CRUD endpoint below and discovery's accept
    flow (`api/v1/discovery.py`, plan D, D-2) both funnel through this: tag
    resolution, encryption (`custom_headers`/`scenario_variables`), the
    heartbeat-slug conflict, default alert-preset wiring, and the audit log.

    Callers own their own permission checks first — `can_create_monitors`
    and `assert_can_assign_group`/`assert_can_assign_team` — this function
    assumes they already passed.
    """
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
        public_name=payload.public_name,
        url=str(payload.url),
        group_id=payload.group_id,
        owner_id=current_user.id,
        team_id=payload.team_id,
        interval_seconds=payload.interval_seconds,
        timeout_seconds=payload.timeout_seconds,
        follow_redirects=payload.follow_redirects,
        expected_status_codes=payload.expected_status_codes,
        enabled=payload.enabled,
        ssl_check_enabled=payload.ssl_check_enabled,
        ssl_expiry_warn_days=payload.ssl_expiry_warn_days,
        ssl_pin_sha256=payload.ssl_pin_sha256,
        ssl_min_chain_days=payload.ssl_min_chain_days,
        tags=tags,
        check_type=payload.check_type,
        tcp_port=payload.tcp_port,
        udp_port=payload.udp_port,
        smtp_port=payload.smtp_port,
        smtp_starttls=payload.smtp_starttls,
        domain_expiry_warn_days=payload.domain_expiry_warn_days,
        dns_record_type=payload.dns_record_type,
        dns_expected_value=payload.dns_expected_value,
        dns_nameservers=payload.dns_nameservers,
        keyword=payload.keyword,
        keyword_negate=payload.keyword_negate,
        expected_json_path=payload.expected_json_path,
        expected_json_value=payload.expected_json_value,
        scenario_steps=(
            [s.model_dump() for s in payload.scenario_steps] if payload.scenario_steps else None
        ),
        scenario_variables=encrypt_scenario_variables(
            [v.model_dump() for v in payload.scenario_variables]
        )
        if payload.scenario_variables
        else None,
        heartbeat_slug=payload.heartbeat_slug,
        heartbeat_token=generate_heartbeat_token() if payload.heartbeat_slug else None,
        heartbeat_interval_seconds=payload.heartbeat_interval_seconds,
        heartbeat_grace_seconds=payload.heartbeat_grace_seconds,
        body_regex=payload.body_regex,
        expected_headers=payload.expected_headers,
        json_schema=payload.json_schema,
        custom_headers=encrypt_custom_headers(payload.custom_headers),
        slo_target=payload.slo_target,
        slo_window_days=payload.slo_window_days,
        dns_drift_alert=payload.dns_drift_alert,
        dns_split_enabled=payload.dns_split_enabled,
        composite_aggregation=payload.composite_aggregation,
        runbook_enabled=payload.runbook_enabled,
        runbook_markdown=payload.runbook_markdown if payload.runbook_enabled else None,
        schema_drift_enabled=payload.schema_drift_enabled,
        health_engine_enabled=payload.health_engine_enabled,
    )
    db.add(monitor)
    try:
        await db.flush()
    except IntegrityError as e:
        await db.rollback()
        if payload.heartbeat_slug and "heartbeat_slug" in str(e.orig):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"heartbeat_slug '{payload.heartbeat_slug}' is already used",
            ) from None
        raise

    # V2 Global Health Engine, plan Cap v2 4a: a monitor created with the
    # engine active must never be silent (CLAUDE.md "Health Engine V2 — ops
    # prod" pitfall #1: engine ON + zero active SLORule = no incident, ever).
    # min_probes=1 — not DEFAULT_RULE_KWARGS' 2 — is what makes the new
    # default safe: a single-probe install (the embedded probe-local on a
    # fresh deployment) behaves exactly like the legacy per-probe decider,
    # and the consensus activates on its own as soon as a second probe
    # reports. Manual toggles / rule deletions afterwards are not
    # re-guaranteed here — see services/health.evaluate_slos, which logs
    # instead so that state stays visible rather than silent.
    if monitor.health_engine_enabled:
        from whatisup.models.monitor_health import SLORule
        from whatisup.scripts.migrate_to_health_engine import DEFAULT_RULE_KWARGS

        db.add(
            SLORule(
                monitor_id=monitor.id,
                **{**DEFAULT_RULE_KWARGS, "min_probes": 1},
            )
        )
        await db.flush()

    # Auto-create alert rules if channels were specified
    if payload.alert_channel_ids:
        from whatisup.models.alert import AlertChannel, AlertRule
        from whatisup.services.alert_presets import get_presets

        channels = list(
            (
                await db.execute(
                    select(AlertChannel).where(
                        AlertChannel.id.in_(payload.alert_channel_ids),
                        AlertChannel.owner_id == current_user.id,
                    )
                )
            )
            .scalars()
            .all()
        )
        if channels:
            for preset in get_presets(monitor.check_type):
                if not preset.get("default", False):
                    continue
                rule = AlertRule(
                    owner_id=current_user.id,
                    monitor_id=monitor.id,
                    condition=preset["condition"],
                    min_duration_seconds=preset.get("min_duration_seconds", 0),
                    threshold_value=preset.get("threshold_value"),
                    channels=channels,
                )
                db.add(rule)
            await db.flush()

    from whatisup.services.audit import log_action

    await log_action(db, "monitor.create", "monitor", monitor.id, monitor.name, current_user)

    return monitor


@router.post("/", response_model=MonitorOut, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
async def create_monitor(
    request: Request,
    payload: MonitorCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Monitor:
    if not current_user.is_superadmin and not current_user.can_create_monitors:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Monitor creation not allowed for your account",
        )
    # SEC-M1: a user must not attach a monitor to a group/team they cannot access.
    await assert_can_assign_group(db, current_user, payload.group_id)
    await assert_can_assign_team(db, current_user, payload.team_id)

    return await _create_monitor_from_payload(db, current_user, payload)


@router.post("/bulk", response_model=BulkActionResponse)
@limiter.limit("20/minute")
async def bulk_action(
    request: Request,
    payload: BulkActionRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Bulk enable / pause / delete monitors owned by the current user."""
    # Access filter — superadmin can act on all; others on own + team resources
    if current_user.is_superadmin:
        ownership_clause = Monitor.id.in_(payload.ids)
    else:
        team_ids = await get_user_team_ids(current_user, db, min_role=TeamRole.editor)
        ownership_clause = and_(
            Monitor.id.in_(payload.ids),
            build_access_filter(Monitor, current_user, team_ids),
        )

    if payload.action == "delete":
        result = await db.execute(delete(Monitor).where(ownership_clause))
        affected = result.rowcount
    elif payload.action == "enable":
        result = await db.execute(update(Monitor).where(ownership_clause).values(enabled=True))
        affected = result.rowcount
    elif payload.action == "pause":
        result = await db.execute(update(Monitor).where(ownership_clause).values(enabled=False))
        affected = result.rowcount
    elif payload.action == "set_group":
        # target_group_id may be None → ungroup. When provided, verify the user can access it.
        if payload.target_group_id is not None:
            grp = (
                await db.execute(
                    select(MonitorGroup).where(MonitorGroup.id == payload.target_group_id)
                )
            ).scalar_one_or_none()
            if grp is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Target group not found"
                )
            if not current_user.is_superadmin:
                await check_resource_access(grp, current_user, db)
        result = await db.execute(
            update(Monitor).where(ownership_clause).values(group_id=payload.target_group_id)
        )
        affected = result.rowcount
    elif payload.action in ("add_tags", "remove_tags"):
        if not payload.tag_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="tag_ids required for tag actions",
            )
        # Validate that all tags exist (cheap, scoped to provided IDs).
        existing = (
            (await db.execute(select(Tag.id).where(Tag.id.in_(payload.tag_ids)))).scalars().all()
        )
        if len(existing) != len(set(payload.tag_ids)):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown tag id")
        # Resolve target monitor IDs once, respecting access.
        target_ids = list(
            (await db.execute(select(Monitor.id).where(ownership_clause))).scalars().all()
        )
        if payload.action == "add_tags":
            # Insert pairs ignoring duplicates (composite PK enforces uniqueness).
            from sqlalchemy.dialects.postgresql import insert as pg_insert
            from sqlalchemy.dialects.sqlite import insert as sqlite_insert

            insert_fn = pg_insert if dialect_name(db) == "postgresql" else sqlite_insert
            for mid in target_ids:
                for tid in set(payload.tag_ids):
                    stmt = insert_fn(monitor_tags).values(monitor_id=mid, tag_id=tid)
                    stmt = stmt.on_conflict_do_nothing(index_elements=["monitor_id", "tag_id"])
                    await db.execute(stmt)
        else:  # remove_tags
            await db.execute(
                delete(monitor_tags).where(
                    monitor_tags.c.monitor_id.in_(target_ids),
                    monitor_tags.c.tag_id.in_(payload.tag_ids),
                )
            )
        affected = len(target_ids)
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown bulk action")

    return {"affected": affected}


@router.get("/{monitor_id}", response_model=MonitorOut)
@limiter.limit("120/minute")
async def get_monitor(
    request: Request,
    monitor_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Monitor:
    return await _get_monitor_or_404(monitor_id, current_user, db)


@router.patch("/{monitor_id}", response_model=MonitorOut)
@limiter.limit("30/minute")
async def update_monitor(
    request: Request,
    monitor_id: uuid.UUID,
    payload: MonitorUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Monitor:
    monitor = await _get_monitor_or_404(monitor_id, current_user, db)

    before = MonitorOut.model_validate(monitor).model_dump(mode="json")

    update_data = payload.model_dump(exclude_unset=True)
    tag_ids = update_data.pop("tag_ids", None)

    # Option B: disabling the runbook wipes its markdown content, regardless
    # of whether runbook_markdown was also present in the payload.
    if update_data.get("runbook_enabled") is False:
        update_data["runbook_markdown"] = None

    # SEC-M1: re-validate group/team reassignment against the caller's access.
    if "group_id" in update_data:
        await assert_can_assign_group(db, current_user, update_data["group_id"])
    if "team_id" in update_data:
        await assert_can_assign_team(db, current_user, update_data["team_id"])

    for field, value in update_data.items():
        if field == "url" and value is not None:
            value = str(value)
        elif field == "scenario_variables" and value is not None:
            # Encrypt secret variables before persisting; skip empty-value entries
            # (empty value means "unchanged" when the UI re-submits masked data)
            non_empty = [v for v in value if not (v.get("secret") and not v.get("value"))]
            value = encrypt_scenario_variables(non_empty)
        elif field == "custom_headers" and value is not None:
            value = encrypt_custom_headers(value)
        setattr(monitor, field, value)

    # Backfill heartbeat_token whenever a slug is set without a token
    # (covers both legacy rows and converting an existing monitor to heartbeat).
    if monitor.heartbeat_slug and not monitor.heartbeat_token:
        monitor.heartbeat_token = generate_heartbeat_token()

    if tag_ids is not None:
        tags_result = await db.execute(select(Tag).where(Tag.id.in_(tag_ids)))
        monitor.tags = list(tags_result.scalars().all())

    try:
        await db.flush()
    except IntegrityError as e:
        await db.rollback()
        if monitor.heartbeat_slug and "heartbeat_slug" in str(e.orig):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"heartbeat_slug '{monitor.heartbeat_slug}' is already used",
            ) from None
        raise

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
@limiter.limit("30/minute")
async def delete_monitor(
    request: Request,
    monitor_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    monitor = await _get_monitor_or_404(monitor_id, current_user, db)
    from whatisup.services.audit import log_action

    await log_action(db, "monitor.delete", "monitor", monitor.id, monitor.name, current_user)
    await db.delete(monitor)


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
