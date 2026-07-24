"""Monitor configuration export / import."""

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.api.deps import (
    assert_can_assign_group,
    build_access_filter,
    get_current_user,
    get_user_team_ids,
)
from whatisup.core.database import get_db
from whatisup.core.limiter import limiter
from whatisup.core.security import encrypt_scenario_variables, generate_heartbeat_token
from whatisup.models.monitor import Monitor
from whatisup.models.user import User
from whatisup.schemas.monitor import (
    MonitorOut,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/monitors", tags=["monitors"])

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

        # SEC-M1 / audit F2: the import payload is raw attacker-controlled JSON.
        # ``group_id`` is a config field, so without this check a user could
        # attach their own monitor to another tenant's group and have it render
        # on the victim's public status page. Mirrors create_monitor /
        # update_monitor, which both call assert_can_assign_group.
        group_id = entry.get("group_id")
        if group_id is not None:
            try:
                group_uuid = uuid.UUID(str(group_id))
            except ValueError:
                errors.append(f"Entry {idx} ({name}): invalid 'group_id'")
                continue
            try:
                await assert_can_assign_group(db, current_user, group_uuid)
            except HTTPException:
                errors.append(f"Entry {idx} ({name}): group not found or not accessible")
                continue
            entry = {**entry, "group_id": group_uuid}

        try:
            data = {k: v for k, v in entry.items() if k in config_fields and v is not None}
            # Secret scenario variables must be Fernet-encrypted at rest exactly
            # like the create/update endpoints do — the import path used to
            # store them verbatim.
            if data.get("scenario_variables"):
                data["scenario_variables"] = encrypt_scenario_variables(data["scenario_variables"])

            if name in existing_by_name:
                # Update existing
                monitor = existing_by_name[name]
                for field, value in data.items():
                    if field in ("name",):
                        continue
                    if field == "url":
                        value = str(value)
                    setattr(monitor, field, value)
                if monitor.heartbeat_slug and not monitor.heartbeat_token:
                    monitor.heartbeat_token = generate_heartbeat_token()
                updated += 1
            else:
                # Create new
                monitor = Monitor(
                    owner_id=current_user.id,
                    **{k: (str(v) if k == "url" else v) for k, v in data.items()},
                )
                if monitor.heartbeat_slug:
                    monitor.heartbeat_token = generate_heartbeat_token()
                db.add(monitor)
                existing_by_name[name] = monitor
                imported += 1
        except Exception:
            logger.exception("Failed to import monitor entry %d (%s)", idx, name)
            errors.append(f"Entry {idx} ({name}): invalid configuration")

    await db.flush()
    return {"imported": imported, "updated": updated, "errors": errors}
