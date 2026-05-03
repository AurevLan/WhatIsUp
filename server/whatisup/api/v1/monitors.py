"""Monitor CRUD endpoints."""

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import and_, delete, func, select, true, update
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.api.deps import (
    build_access_filter,
    check_resource_access,
    get_current_user,
    get_user_team_ids,
    require_superadmin,
)
from whatisup.core.database import dialect_name, get_db
from whatisup.core.limiter import limiter
from whatisup.core.security import encrypt_scenario_variables
from whatisup.models.annotation import MonitorAnnotation
from whatisup.models.monitor import CompositeMonitorMember, Monitor, MonitorGroup, monitor_tags
from whatisup.models.probe import Probe
from whatisup.models.result import CheckResult
from whatisup.models.tag import Tag
from whatisup.models.team import TeamRole
from whatisup.models.user import User
from whatisup.schemas.annotation import AnnotationCreate, AnnotationOut
from whatisup.schemas.incident import IncidentOut
from whatisup.schemas.monitor import (
    BulkActionRequest,
    BulkActionResponse,
    CompositeMonitorMemberCreate,
    CompositeMonitorMemberOut,
    MonitorCreate,
    MonitorDependencyCreate,
    MonitorDependencyOut,
    MonitorOut,
    MonitorUpdate,
)
from whatisup.schemas.probe import ProbeMonitorStatus
from whatisup.schemas.result import CheckResultOut, UptimeStats
from whatisup.services.stats import compute_uptime, compute_uptime_bulk, compute_uptime_in_range

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/monitors", tags=["monitors"])


async def _get_monitor_or_404(
    monitor_id: uuid.UUID,
    user: User,
    db: AsyncSession,
    min_role: TeamRole = TeamRole.viewer,
) -> Monitor:
    monitor = (
        await db.execute(select(Monitor).where(Monitor.id == monitor_id))
    ).scalar_one_or_none()
    if monitor is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Monitor not found")
    await check_resource_access(monitor, user, db, min_role=min_role)
    return monitor


@router.get("/", response_model=list[MonitorOut])
async def list_monitors(
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

    # Latest status per monitor (one query — join on max checked_at)
    max_ts_subq = (
        select(
            CheckResult.monitor_id,
            func.max(CheckResult.checked_at).label("max_at"),
        )
        .where(CheckResult.monitor_id.in_(monitor_ids))
        .group_by(CheckResult.monitor_id)
        .subquery()
    )
    latest_rows = (
        await db.execute(
            select(CheckResult.monitor_id, CheckResult.status, CheckResult.checked_at).join(
                max_ts_subq,
                and_(
                    CheckResult.monitor_id == max_ts_subq.c.monitor_id,
                    CheckResult.checked_at == max_ts_subq.c.max_at,
                ),
            )
        )
    ).all()
    # Map: monitor_id → (status_value, checked_at)
    latest_map = {str(r.monitor_id): (r.status.value, r.checked_at) for r in latest_rows}

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

    # Last response time per monitor (reuse latest result subquery)
    rt_rows = (
        await db.execute(
            select(CheckResult.monitor_id, CheckResult.response_time_ms).join(
                max_ts_subq,
                and_(
                    CheckResult.monitor_id == max_ts_subq.c.monitor_id,
                    CheckResult.checked_at == max_ts_subq.c.max_at,
                ),
            )
        )
    ).all()
    rt_map = {
        str(r.monitor_id): round(r.response_time_ms, 1)
        for r in rt_rows
        if r.response_time_ms is not None
    }

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

    now = datetime.now(UTC)
    out = []
    for m in monitors:
        mid = str(m.id)
        d = MonitorOut.model_validate(m).model_dump()
        entry = latest_map.get(mid)
        if entry:
            status_val, checked_at = entry
            age = (now - checked_at).total_seconds()
            threshold = max(300, m.interval_seconds * 3)
            d["last_status"] = status_val if age < threshold else None
        else:
            d["last_status"] = None
        d["uptime_24h"] = uptime_map.get(mid)
        d["last_response_time_ms"] = rt_map.get(mid)
        d["p95_response_time_ms"] = p95_map.get(mid)
        d["sparkline"] = sparkline_map.get(mid, [])
        out.append(d)
    return out


# ── Export / Import configuration ──────────────────────────────────────────


# Fields to strip from export (runtime / server-managed)
_EXPORT_STRIP_FIELDS = {
    "id",
    "owner_id",
    "team_id",
    "created_at",
    "updated_at",
    "last_status",
    "uptime_24h",
    "last_response_time_ms",
    "p95_response_time_ms",
    "sparkline",
    "last_heartbeat_at",
    "schema_baseline",
    "schema_baseline_updated_at",
    "dns_baseline_ips",
}


@router.get("/export")
@limiter.limit("10/minute")
async def export_monitors(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Export all user's monitors as a JSON array of configurations."""
    query = select(Monitor)
    if not current_user.is_superadmin:
        team_ids = await get_user_team_ids(current_user, db)
        query = query.where(build_access_filter(Monitor, current_user, team_ids))
    monitors = list((await db.execute(query.order_by(Monitor.created_at.desc()))).scalars().all())
    out = []
    for m in monitors:
        d = MonitorOut.model_validate(m).model_dump(mode="json")
        for key in _EXPORT_STRIP_FIELDS:
            d.pop(key, None)
        out.append(d)
    return out


class ImportResult(BaseModel):
    imported: int = 0
    updated: int = 0
    errors: list[str] = []


@router.post("/import", response_model=ImportResult)
@limiter.limit("5/minute")
async def import_monitors(
    request: Request,
    monitors_data: list[dict[str, Any]] = Body(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Import monitors from a JSON array. Upserts by name."""
    if not current_user.is_superadmin and not current_user.can_create_monitors:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Monitor creation not allowed for your account",
        )

    imported = 0
    updated = 0
    errors: list[str] = []

    # Pre-load existing monitors by name for this user
    existing_query = select(Monitor)
    if not current_user.is_superadmin:
        team_ids = await get_user_team_ids(current_user, db)
        existing_query = existing_query.where(build_access_filter(Monitor, current_user, team_ids))
    existing = (await db.execute(existing_query)).scalars().all()
    existing_by_name = {m.name: m for m in existing}

    # Config fields that map to Monitor columns
    config_fields = {
        "name",
        "url",
        "group_id",
        "interval_seconds",
        "timeout_seconds",
        "follow_redirects",
        "expected_status_codes",
        "enabled",
        "ssl_check_enabled",
        "ssl_expiry_warn_days",
        "ssl_pin_sha256",
        "ssl_min_chain_days",
        "check_type",
        "tcp_port",
        "udp_port",
        "smtp_port",
        "smtp_starttls",
        "domain_expiry_warn_days",
        "dns_record_type",
        "dns_expected_value",
        "dns_nameservers",
        "dns_drift_alert",
        "dns_split_enabled",
        "dns_baseline_ips_internal",
        "dns_baseline_ips_external",
        "composite_aggregation",
        "keyword",
        "keyword_negate",
        "expected_json_path",
        "expected_json_value",
        "scenario_steps",
        "scenario_variables",
        "heartbeat_slug",
        "heartbeat_interval_seconds",
        "heartbeat_grace_seconds",
        "body_regex",
        "expected_headers",
        "json_schema",
        "custom_headers",
        "slo_target",
        "slo_window_days",
        "network_scope",
        "flap_threshold",
        "flap_window_minutes",
        "auto_pause_after",
        "data_retention_days",
        "schema_drift_enabled",
    }

    for idx, entry in enumerate(monitors_data):
        name = entry.get("name")
        if not name:
            errors.append(f"Entry {idx}: missing 'name' field")
            continue
        url = entry.get("url")
        if not url:
            errors.append(f"Entry {idx} ({name}): missing 'url' field")
            continue

        try:
            data = {k: v for k, v in entry.items() if k in config_fields and v is not None}

            if name in existing_by_name:
                # Update existing
                monitor = existing_by_name[name]
                for field, value in data.items():
                    if field in ("name",):
                        continue
                    if field == "url":
                        value = str(value)
                    setattr(monitor, field, value)
                updated += 1
            else:
                # Create new
                monitor = Monitor(
                    owner_id=current_user.id,
                    **{k: (str(v) if k == "url" else v) for k, v in data.items()},
                )
                db.add(monitor)
                existing_by_name[name] = monitor
                imported += 1
        except Exception:
            logger.exception("Failed to import monitor entry %d (%s)", idx, name)
            errors.append(f"Entry {idx} ({name}): invalid configuration")

    await db.flush()
    return {"imported": imported, "updated": updated, "errors": errors}


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
        heartbeat_interval_seconds=payload.heartbeat_interval_seconds,
        heartbeat_grace_seconds=payload.heartbeat_grace_seconds,
        body_regex=payload.body_regex,
        expected_headers=payload.expected_headers,
        json_schema=payload.json_schema,
        custom_headers=payload.custom_headers,
        slo_target=payload.slo_target,
        slo_window_days=payload.slo_window_days,
        dns_drift_alert=payload.dns_drift_alert,
        dns_split_enabled=payload.dns_split_enabled,
        composite_aggregation=payload.composite_aggregation,
        runbook_enabled=payload.runbook_enabled,
        runbook_markdown=payload.runbook_markdown if payload.runbook_enabled else None,
    )
    db.add(monitor)
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
            await db.execute(select(Tag.id).where(Tag.id.in_(payload.tag_ids)))
        ).scalars().all()
        if len(existing) != len(set(payload.tag_ids)):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown tag id"
            )
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
                    stmt = stmt.on_conflict_do_nothing(
                        index_elements=["monitor_id", "tag_id"]
                    )
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
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown bulk action"
        )

    return {"affected": affected}


@router.get("/graph")
@limiter.limit("30/minute")
async def get_dependency_graph(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return the full monitor dependency graph for the current user.

    Declared BEFORE ``/{monitor_id}`` on purpose: FastAPI matches paths in
    declaration order, so the literal ``/graph`` would otherwise be consumed
    by the parameterized route and fail UUID validation with 422.

    Nodes: all accessible monitors with their current status.
    Edges: all dependencies between those monitors.
    """
    from whatisup.models.monitor import MonitorDependency

    # Fetch all accessible monitors
    query = select(Monitor)
    if not current_user.is_superadmin:
        team_ids = await get_user_team_ids(current_user, db)
        query = query.where(build_access_filter(Monitor, current_user, team_ids))
    monitors = list((await db.execute(query)).scalars().all())

    monitor_ids = [m.id for m in monitors]
    monitor_id_set = {m.id for m in monitors}

    # Latest status per monitor
    nodes = []
    latest_map: dict = {}
    if monitor_ids:
        max_ts_subq = (
            select(
                CheckResult.monitor_id,
                func.max(CheckResult.checked_at).label("max_at"),
            )
            .where(CheckResult.monitor_id.in_(monitor_ids))
            .group_by(CheckResult.monitor_id)
            .subquery()
        )
        latest_rows = (
            await db.execute(
                select(CheckResult.monitor_id, CheckResult.status, CheckResult.checked_at).join(
                    max_ts_subq,
                    and_(
                        CheckResult.monitor_id == max_ts_subq.c.monitor_id,
                        CheckResult.checked_at == max_ts_subq.c.max_at,
                    ),
                )
            )
        ).all()
        now = datetime.now(UTC)
        for r in latest_rows:
            age = (now - r.checked_at).total_seconds()
            latest_map[r.monitor_id] = r.status.value if age < 300 else None

    for m in monitors:
        nodes.append(
            {
                "id": str(m.id),
                "name": m.name,
                "status": latest_map.get(m.id),
                "check_type": m.check_type,
            }
        )

    # Fetch all dependencies between accessible monitors only
    edges = []
    if monitor_ids:
        dep_rows = (
            (
                await db.execute(
                    select(MonitorDependency).where(
                        MonitorDependency.parent_id.in_(monitor_ids),
                        MonitorDependency.child_id.in_(monitor_ids),
                    )
                )
            )
            .scalars()
            .all()
        )
        for dep in dep_rows:
            if dep.parent_id in monitor_id_set and dep.child_id in monitor_id_set:
                edges.append(
                    {
                        "source": str(dep.parent_id),
                        "target": str(dep.child_id),
                        "suppress_on_parent_down": dep.suppress_on_parent_down,
                    }
                )

    return {"nodes": nodes, "edges": edges}


@router.get("/{monitor_id}", response_model=MonitorOut)
async def get_monitor(
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

    for field, value in update_data.items():
        if field == "url" and value is not None:
            value = str(value)
        elif field == "scenario_variables" and value is not None:
            # Encrypt secret variables before persisting; skip empty-value entries
            # (empty value means "unchanged" when the UI re-submits masked data)
            non_empty = [v for v in value if not (v.get("secret") and not v.get("value"))]
            value = encrypt_scenario_variables(non_empty)
        setattr(monitor, field, value)

    if tag_ids is not None:
        tags_result = await db.execute(select(Tag).where(Tag.id.in_(tag_ids)))
        monitor.tags = list(tags_result.scalars().all())

    await db.flush()

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


@router.get("/{monitor_id}/results", response_model=list[CheckResultOut])
async def get_results(
    monitor_id: uuid.UUID,
    limit: int = Query(default=100, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
    since: datetime | None = Query(
        default=None, description="ISO datetime — only results after this timestamp"
    ),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list:
    await _get_monitor_or_404(monitor_id, current_user, db)
    query = select(CheckResult).where(CheckResult.monitor_id == monitor_id)
    if since is not None:
        query = query.where(CheckResult.checked_at >= since)
    query = query.order_by(CheckResult.checked_at.desc()).limit(limit).offset(offset)
    result = await db.execute(query)
    return list(result.scalars().all())


@router.get("/{monitor_id}/uptime", response_model=UptimeStats)
async def get_uptime(
    monitor_id: uuid.UUID,
    period_hours: int = Query(default=24, ge=1, le=2160),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UptimeStats:
    await _get_monitor_or_404(monitor_id, current_user, db)
    return await compute_uptime(db, monitor_id, period_hours)


@router.get("/{monitor_id}/history", response_model=list[dict])
async def get_history(
    monitor_id: uuid.UUID,
    days: int = Query(default=90, ge=1, le=365),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Daily uptime history for the last N days (for history bars UI)."""
    await _get_monitor_or_404(monitor_id, current_user, db)
    from whatisup.services.stats import compute_daily_history

    return await compute_daily_history(db, monitor_id, days)


@router.get("/{monitor_id}/percentiles")
@limiter.limit("60/minute")
async def get_percentiles(
    monitor_id: uuid.UUID,
    request: Request,
    hours: int = Query(default=24, ge=1, le=720),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """P50/P95/P99 response time percentiles over time buckets."""
    await _get_monitor_or_404(monitor_id, current_user, db)
    from whatisup.services.stats import compute_percentile_timeseries

    return await compute_percentile_timeseries(db, monitor_id, hours=hours)


@router.get("/{monitor_id}/probes", response_model=list[ProbeMonitorStatus])
async def get_monitor_probe_status(
    monitor_id: uuid.UUID,
    _user: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Last check result per probe for a given monitor."""
    # Subquery: MAX(checked_at) per probe_id for this monitor
    max_ts_subq = (
        select(
            CheckResult.probe_id,
            func.max(CheckResult.checked_at).label("max_at"),
        )
        .where(CheckResult.monitor_id == monitor_id)
        .group_by(CheckResult.probe_id)
        .subquery()
    )

    # Latest result row per probe
    latest_rows = (
        await db.execute(
            select(
                CheckResult.probe_id,
                CheckResult.status,
                CheckResult.checked_at,
                CheckResult.response_time_ms,
            ).join(
                max_ts_subq,
                and_(
                    CheckResult.probe_id == max_ts_subq.c.probe_id,
                    CheckResult.checked_at == max_ts_subq.c.max_at,
                    CheckResult.monitor_id == monitor_id,
                ),
            )
        )
    ).all()
    latest_map = {str(r.probe_id): r for r in latest_rows}

    # All probes
    probes = list((await db.execute(select(Probe).order_by(Probe.name))).scalars().all())

    out = []
    for p in probes:
        row = latest_map.get(str(p.id))
        out.append(
            ProbeMonitorStatus(
                probe_id=p.id,
                name=p.name,
                location_name=p.location_name,
                latitude=p.latitude,
                longitude=p.longitude,
                is_active=p.is_active,
                last_seen_at=p.last_seen_at,
                last_status=row.status if row else None,
                last_checked_at=row.checked_at if row else None,
                response_time_ms=row.response_time_ms if row else None,
            )
        )
    return out


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


@router.get("/{monitor_id}/incidents", response_model=list[IncidentOut])
async def get_incidents(
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
async def get_postmortem(
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


@router.get("/{monitor_id}/report")
@limiter.limit("20/minute")
async def get_sla_report(
    request: Request,
    monitor_id: uuid.UUID,
    from_: datetime = Query(alias="from", description="ISO datetime start"),
    to: datetime = Query(default=None, description="ISO datetime end (default: now)"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """SLA report for a custom date range."""
    await _get_monitor_or_404(monitor_id, current_user, db)
    if to is None:
        to = datetime.now(UTC)

    consensus = await compute_uptime_in_range(db, monitor_id, from_, to)

    # Count incidents in period
    from whatisup.models.incident import Incident

    inc_result = await db.execute(
        select(
            func.count(Incident.id).label("count"),
            func.sum(Incident.duration_seconds).label("total_downtime"),
        ).where(
            Incident.monitor_id == monitor_id,
            Incident.started_at >= from_,
            Incident.started_at <= to,
        )
    )
    inc_row = inc_result.one()

    return {
        "monitor_id": str(monitor_id),
        "from": from_.isoformat(),
        "to": to.isoformat(),
        **consensus,
        "incident_count": int(inc_row.count or 0),
        "total_downtime_seconds": int(inc_row.total_downtime or 0),
    }


@router.get("/{monitor_id}/annotations")
async def list_annotations(
    monitor_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    await _get_monitor_or_404(monitor_id, current_user, db)
    rows = (
        (
            await db.execute(
                select(MonitorAnnotation)
                .where(MonitorAnnotation.monitor_id == monitor_id)
                .order_by(MonitorAnnotation.annotated_at.desc())
                .limit(200)
            )
        )
        .scalars()
        .all()
    )
    return [AnnotationOut.model_validate(r).model_dump(mode="json") for r in rows]


@router.post("/{monitor_id}/annotations", status_code=status.HTTP_201_CREATED)
async def create_annotation(
    monitor_id: uuid.UUID,
    payload: AnnotationCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await _get_monitor_or_404(monitor_id, current_user, db)
    ann = MonitorAnnotation(
        monitor_id=monitor_id,
        content=payload.content,
        annotated_at=payload.annotated_at,
        created_at=datetime.now(UTC),
        created_by=current_user.username,
    )
    db.add(ann)
    await db.flush()
    return AnnotationOut.model_validate(ann).model_dump(mode="json")


@router.delete("/{monitor_id}/annotations/{annotation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_annotation(
    monitor_id: uuid.UUID,
    annotation_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await _get_monitor_or_404(monitor_id, current_user, db)
    ann = (
        await db.execute(
            select(MonitorAnnotation).where(
                MonitorAnnotation.id == annotation_id,
                MonitorAnnotation.monitor_id == monitor_id,
            )
        )
    ).scalar_one_or_none()
    if ann is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Annotation not found")
    await db.delete(ann)


@router.get("/{monitor_id}/slo")
@limiter.limit("30/minute")
async def get_slo(
    request: Request,
    monitor_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """SLO / Error Budget status for a monitor."""
    from whatisup.models.incident import Incident

    monitor = await _get_monitor_or_404(monitor_id, current_user, db)

    if monitor.slo_target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="SLO non configuré sur ce moniteur",
        )

    window_days = monitor.slo_window_days or 30
    slo_target = monitor.slo_target
    now = datetime.now(UTC)
    window_start = now - timedelta(days=window_days)

    # Uptime over the SLO window (multi-probe consensus)
    consensus_slo = await compute_uptime_in_range(db, monitor_id, window_start, now)
    uptime_pct = consensus_slo["uptime_percent"]

    # Downtime from resolved incidents in the window
    inc_row = (
        await db.execute(
            select(
                func.coalesce(func.sum(Incident.duration_seconds), 0).label("total_downtime_s"),
            ).where(
                Incident.monitor_id == monitor_id,
                Incident.started_at >= window_start,
                Incident.resolved_at.isnot(None),
            )
        )
    ).one()
    downtime_minutes = float(inc_row.total_downtime_s or 0) / 60.0

    # Error budget calculation
    error_budget_total_minutes = window_days * 24 * 60 * (1 - slo_target / 100)
    error_budget_remaining_minutes = error_budget_total_minutes - downtime_minutes
    error_budget_used_minutes = downtime_minutes
    burn_rate = (
        downtime_minutes / error_budget_total_minutes if error_budget_total_minutes > 0 else 0.0
    )

    if burn_rate >= 1.0:
        slo_status = "exhausted"
    elif burn_rate > 0.8:
        slo_status = "critical"
    elif burn_rate > 0.5:
        slo_status = "at_risk"
    else:
        slo_status = "healthy"

    return {
        "slo_target": slo_target,
        "window_days": window_days,
        "uptime_pct": uptime_pct,
        "error_budget_total_minutes": round(error_budget_total_minutes, 2),
        "error_budget_used_minutes": round(error_budget_used_minutes, 2),
        "error_budget_remaining_minutes": round(error_budget_remaining_minutes, 2),
        "burn_rate": round(burn_rate, 4),
        "status": slo_status,
    }


# ---------------------------------------------------------------------------
# Monitor dependencies
# ---------------------------------------------------------------------------


# NOTE: `/graph` is declared higher up (above `/{monitor_id}`) so FastAPI's
# declaration-order route matcher doesn't try to parse "graph" as a UUID
# monitor_id (which would 422). See get_dependency_graph.


@router.get(
    "/{monitor_id}/dependencies",
    response_model=list[MonitorDependencyOut],
)
@limiter.limit("60/minute")
async def list_dependencies(
    request: Request,
    monitor_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list:
    """List all parent monitors this monitor depends on."""
    from whatisup.models.monitor import MonitorDependency

    await _get_monitor_or_404(monitor_id, current_user, db)
    rows = (
        (
            await db.execute(
                select(MonitorDependency).where(MonitorDependency.child_id == monitor_id)
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


@router.post(
    "/{monitor_id}/dependencies",
    response_model=MonitorDependencyOut,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("30/minute")
async def add_dependency(
    request: Request,
    monitor_id: uuid.UUID,
    payload: MonitorDependencyCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> object:
    """Declare that this monitor depends on a parent monitor.

    When the parent has an open incident and ``suppress_on_parent_down`` is
    ``true``, incidents on this (child) monitor will be suppressed.
    """
    from whatisup.models.monitor import MonitorDependency

    child = await _get_monitor_or_404(monitor_id, current_user, db)
    parent = await _get_monitor_or_404(payload.parent_id, current_user, db)

    if parent.id == child.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A monitor cannot depend on itself",
        )

    # Check for duplicates
    existing = (
        await db.execute(
            select(MonitorDependency).where(
                MonitorDependency.parent_id == parent.id,
                MonitorDependency.child_id == child.id,
            )
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Dependency already exists",
        )

    dep = MonitorDependency(
        parent_id=parent.id,
        child_id=child.id,
        suppress_on_parent_down=payload.suppress_on_parent_down,
    )
    db.add(dep)
    await db.flush()
    return dep


@router.delete(
    "/{monitor_id}/dependencies/{dependency_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_dependency(
    monitor_id: uuid.UUID,
    dependency_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Remove a parent dependency from this monitor."""
    from whatisup.models.monitor import MonitorDependency

    await _get_monitor_or_404(monitor_id, current_user, db)
    dep = (
        await db.execute(
            select(MonitorDependency).where(
                MonitorDependency.id == dependency_id,
                MonitorDependency.child_id == monitor_id,
            )
        )
    ).scalar_one_or_none()
    if dep is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dependency not found")
    await db.delete(dep)


# ---------------------------------------------------------------------------
# DNS baseline management
# ---------------------------------------------------------------------------


@router.post("/{monitor_id}/dns-baseline/accept", status_code=status.HTTP_200_OK)
@limiter.limit("20/minute")
async def accept_dns_baseline(
    request: Request,
    monitor_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Accept the current DNS resolved values as the new baseline.

    Fetches the most recent successful DNS check result for this monitor
    and stores its resolved IPs as the new drift-detection baseline.
    Clears any existing open incident caused by a drift.
    """
    monitor = await _get_monitor_or_404(monitor_id, current_user, db)
    if monitor.check_type != "dns":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="DNS baseline only applies to dns check_type monitors",
        )

    latest = (
        await db.execute(
            select(CheckResult)
            .where(
                CheckResult.monitor_id == monitor_id,
                CheckResult.dns_resolved_values.isnot(None),
            )
            .order_by(CheckResult.checked_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    if latest is None or not latest.dns_resolved_values:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No DNS result available yet — wait for the first check",
        )

    new_baseline = sorted(latest.dns_resolved_values)
    monitor.dns_baseline_ips = new_baseline
    await db.flush()

    return {"baseline": new_baseline, "accepted_at": latest.checked_at.isoformat()}


@router.delete("/{monitor_id}/dns-baseline", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("20/minute")
async def reset_dns_baseline(
    request: Request,
    monitor_id: uuid.UUID,
    type: str = Query(default="all", pattern=r"^(all|internal|external)$"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Clear the DNS baseline — the next successful check will re-learn it.

    type=all (default): clears all baselines (global, internal, external)
    type=internal: clears only the internal probe baseline
    type=external: clears only the external probe baseline
    """
    monitor = await _get_monitor_or_404(monitor_id, current_user, db)
    if monitor.check_type != "dns":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="DNS baseline only applies to dns check_type monitors",
        )
    if type == "internal":
        monitor.dns_baseline_ips_internal = None
    elif type == "external":
        monitor.dns_baseline_ips_external = None
    else:
        monitor.dns_baseline_ips = None
        monitor.dns_baseline_ips_internal = None
        monitor.dns_baseline_ips_external = None


# ---------------------------------------------------------------------------
# Schema drift baseline management
# ---------------------------------------------------------------------------


@router.post("/{monitor_id}/schema-baseline/accept", status_code=status.HTTP_200_OK)
@limiter.limit("20/minute")
async def accept_schema_baseline(
    request: Request,
    monitor_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Accept the current API schema fingerprint as the new baseline for drift detection."""
    from datetime import UTC, datetime

    monitor = await _get_monitor_or_404(monitor_id, current_user, db)

    latest = (
        await db.execute(
            select(CheckResult)
            .where(
                CheckResult.monitor_id == monitor_id,
                CheckResult.schema_fingerprint.isnot(None),
            )
            .order_by(CheckResult.checked_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    if latest is None or not latest.schema_fingerprint:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "No schema fingerprint available yet — "
                "enable schema_drift_enabled and wait for a check"
            ),
        )

    monitor.schema_baseline = latest.schema_fingerprint
    monitor.schema_baseline_updated_at = datetime.now(UTC)

    return {
        "baseline": monitor.schema_baseline,
        "accepted_at": latest.checked_at.isoformat(),
    }


@router.delete("/{monitor_id}/schema-baseline", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("20/minute")
async def reset_schema_baseline(
    request: Request,
    monitor_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Clear the schema baseline — the next successful check will set a new one."""
    monitor = await _get_monitor_or_404(monitor_id, current_user, db)
    monitor.schema_baseline = None
    monitor.schema_baseline_updated_at = None


# ---------------------------------------------------------------------------
# Composite monitor members
# ---------------------------------------------------------------------------


async def _would_create_cycle(
    db: AsyncSession,
    composite_id: uuid.UUID,
    member_id: uuid.UUID,
) -> bool:
    """Check if adding member_id to composite_id would create a cycle.

    Iterative BFS with a single edge query: scales linearly in edges rather
    than issuing one query per node (the previous recursive implementation
    was O(nodes) round-trips).
    """
    if member_id == composite_id:
        return True

    # Load every composite edge once; building the adjacency map in Python
    # turns the cycle check into pure in-memory graph traversal.
    edges = (
        await db.execute(
            select(
                CompositeMonitorMember.composite_id,
                CompositeMonitorMember.monitor_id,
            )
        )
    ).all()
    adjacency: dict[uuid.UUID, list[uuid.UUID]] = {}
    for parent, child in edges:
        adjacency.setdefault(parent, []).append(child)

    visited: set[uuid.UUID] = set()
    queue: list[uuid.UUID] = [member_id]
    while queue:
        node = queue.pop()
        if node in visited:
            continue
        if node == composite_id:
            return True
        visited.add(node)
        queue.extend(adjacency.get(node, ()))
    return False


@router.get(
    "/{monitor_id}/composite-members",
    response_model=list[CompositeMonitorMemberOut],
)
@limiter.limit("60/minute")
async def list_composite_members(
    request: Request,
    monitor_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list:
    """List all source monitors of a composite monitor."""
    monitor = await _get_monitor_or_404(monitor_id, current_user, db)
    if monitor.check_type != "composite":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This monitor is not a composite monitor",
        )
    rows = (
        (
            await db.execute(
                select(CompositeMonitorMember).where(
                    CompositeMonitorMember.composite_id == monitor_id
                )
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


@router.post(
    "/{monitor_id}/composite-members",
    response_model=CompositeMonitorMemberOut,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("30/minute")
async def add_composite_member(
    request: Request,
    monitor_id: uuid.UUID,
    payload: CompositeMonitorMemberCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> object:
    """Add a source monitor to a composite monitor."""
    composite = await _get_monitor_or_404(monitor_id, current_user, db)
    if composite.check_type != "composite":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Target monitor is not a composite monitor",
        )
    if payload.monitor_id == monitor_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A composite monitor cannot reference itself",
        )

    member_monitor = await _get_monitor_or_404(payload.monitor_id, current_user, db)

    # Cycle detection: if member is itself a composite, check for transitive cycles
    if member_monitor.check_type == "composite":
        if await _would_create_cycle(db, monitor_id, payload.monitor_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Adding this member would create a circular dependency",
            )

    existing = (
        await db.execute(
            select(CompositeMonitorMember).where(
                CompositeMonitorMember.composite_id == monitor_id,
                CompositeMonitorMember.monitor_id == payload.monitor_id,
            )
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Member already added")

    member = CompositeMonitorMember(
        composite_id=monitor_id,
        monitor_id=payload.monitor_id,
        weight=payload.weight,
        role=payload.role,
    )
    db.add(member)
    await db.flush()
    return member


@router.patch(
    "/{monitor_id}/composite-members/{member_id}",
    response_model=CompositeMonitorMemberOut,
)
@limiter.limit("30/minute")
async def update_composite_member(
    request: Request,
    monitor_id: uuid.UUID,
    member_id: uuid.UUID,
    payload: CompositeMonitorMemberCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> object:
    """Update weight or role of a composite member."""
    await _get_monitor_or_404(monitor_id, current_user, db)
    member = (
        await db.execute(
            select(CompositeMonitorMember).where(
                CompositeMonitorMember.id == member_id,
                CompositeMonitorMember.composite_id == monitor_id,
            )
        )
    ).scalar_one_or_none()
    if member is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")
    member.weight = payload.weight
    member.role = payload.role
    await db.flush()
    return member


@router.delete(
    "/{monitor_id}/composite-members/{member_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_composite_member(
    monitor_id: uuid.UUID,
    member_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Remove a source monitor from a composite monitor."""
    await _get_monitor_or_404(monitor_id, current_user, db)
    member = (
        await db.execute(
            select(CompositeMonitorMember).where(
                CompositeMonitorMember.id == member_id,
                CompositeMonitorMember.composite_id == monitor_id,
            )
        )
    ).scalar_one_or_none()
    if member is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")
    await db.delete(member)


# ── Correlation patterns ─────────────────────────────────────────────────


@router.get("/{monitor_id}/correlated")
async def get_correlated_monitors(
    monitor_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Return monitors that frequently fail at the same time as this one."""
    await _get_monitor_or_404(monitor_id, current_user, db)
    from whatisup.services.correlation import get_correlated_monitors as _get

    patterns = await _get(db, monitor_id)
    # Enrich with monitor names
    if patterns:
        monitor_ids = [uuid.UUID(p["monitor_id"]) for p in patterns]
        monitors = (
            await db.execute(select(Monitor.id, Monitor.name).where(Monitor.id.in_(monitor_ids)))
        ).all()
        name_map = {str(m.id): m.name for m in monitors}
        for p in patterns:
            p["monitor_name"] = name_map.get(p["monitor_id"])
    return patterns
