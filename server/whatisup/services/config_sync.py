"""Declarative configuration export and import (Infrastructure-as-Code)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from whatisup.core.security import decrypt_channel_config, encrypt_channel_config
from whatisup.models.alert import AlertChannel, AlertChannelType, AlertCondition, AlertRule
from whatisup.models.monitor import Monitor, MonitorGroup
from whatisup.models.user import User

logger = structlog.get_logger(__name__)

# Fields to include in monitor export (excludes internal/computed fields)
_MONITOR_EXPORT_FIELDS = [
    "name", "url", "check_type", "interval_seconds", "timeout_seconds",
    "follow_redirects", "expected_status_codes", "enabled",
    "ssl_check_enabled", "ssl_expiry_warn_days",
    "tcp_port", "udp_port", "smtp_port", "smtp_starttls",
    "domain_expiry_warn_days", "dns_record_type", "dns_expected_value", "dns_nameservers",
    "dns_drift_alert", "dns_split_enabled",
    "keyword", "keyword_negate",
    "expected_json_path", "expected_json_value",
    "body_regex", "expected_headers", "json_schema",
    "schema_drift_enabled",
    "slo_target", "slo_window_days", "network_scope",
    "flap_threshold", "flap_window_minutes", "auto_pause_after",
    "heartbeat_slug", "heartbeat_interval_seconds", "heartbeat_grace_seconds",
    "scenario_steps", "scenario_variables",
    "composite_aggregation",
]


async def export_config(user: User, db: AsyncSession) -> dict[str, Any]:
    """Export the full monitoring configuration for the user as a dict."""
    # Groups
    groups_q = select(MonitorGroup).order_by(MonitorGroup.name)
    if not user.is_superadmin:
        groups_q = groups_q.where(MonitorGroup.owner_id == user.id)
    groups = (await db.execute(groups_q)).scalars().all()

    groups_export = []
    group_names_by_id: dict[uuid.UUID, str] = {}
    for g in groups:
        group_names_by_id[g.id] = g.name
        groups_export.append({
            "name": g.name,
            "description": g.description,
            "public_slug": g.public_slug,
            "custom_logo_url": g.custom_logo_url,
            "accent_color": g.accent_color,
            "announcement_banner": g.announcement_banner,
            "report_schedule": g.report_schedule,
            "report_emails": g.report_emails,
        })

    # Monitors
    monitors_q = select(Monitor).order_by(Monitor.name)
    if not user.is_superadmin:
        monitors_q = monitors_q.where(Monitor.owner_id == user.id)
    monitors = (await db.execute(monitors_q)).scalars().all()

    monitors_export = []
    for m in monitors:
        entry: dict[str, Any] = {}
        for field in _MONITOR_EXPORT_FIELDS:
            val = getattr(m, field, None)
            if val is not None and val != _get_default(field):
                entry[field] = val
        # Always include name, url, check_type
        entry["name"] = m.name
        entry["url"] = m.url
        entry["check_type"] = m.check_type
        # Resolve group name
        if m.group_id and m.group_id in group_names_by_id:
            entry["group"] = group_names_by_id[m.group_id]
        monitors_export.append(entry)

    # Alert channels (secrets redacted)
    channels_q = select(AlertChannel).order_by(AlertChannel.name)
    if not user.is_superadmin:
        channels_q = channels_q.where(AlertChannel.owner_id == user.id)
    channels = (await db.execute(channels_q)).scalars().all()

    channel_names_by_id: dict[uuid.UUID, str] = {}
    channels_export = []
    for c in channels:
        channel_names_by_id[c.id] = c.name
        channels_export.append({
            "name": c.name,
            "type": c.type.value,
            "config": _redact_config(decrypt_channel_config(c.config), c.type),
        })

    # Alert rules
    rules_q = (
        select(AlertRule)
        .options(selectinload(AlertRule.channels))
        .order_by(AlertRule.created_at)
    )
    if not user.is_superadmin:
        monitor_ids = [m.id for m in monitors]
        group_ids = [g.id for g in groups]
        from sqlalchemy import or_
        conditions = []
        if monitor_ids:
            conditions.append(AlertRule.monitor_id.in_(monitor_ids))
        if group_ids:
            conditions.append(AlertRule.group_id.in_(group_ids))
        if conditions:
            rules_q = rules_q.where(or_(*conditions))
        else:
            rules_q = rules_q.where(AlertRule.id == None)  # noqa: E711

    rules = (await db.execute(rules_q)).scalars().all()

    monitor_names_by_id = {m.id: m.name for m in monitors}
    rules_export = []
    for r in rules:
        rule_entry: dict[str, Any] = {
            "condition": r.condition.value,
            "channels": [
                channel_names_by_id[c.id]
                for c in r.channels
                if c.id in channel_names_by_id
            ],
        }
        if r.monitor_id and r.monitor_id in monitor_names_by_id:
            rule_entry["monitor"] = monitor_names_by_id[r.monitor_id]
        if r.group_id and r.group_id in group_names_by_id:
            rule_entry["group"] = group_names_by_id[r.group_id]
        if r.threshold_value is not None:
            rule_entry["threshold_value"] = r.threshold_value
        if r.min_duration_seconds:
            rule_entry["min_duration_seconds"] = r.min_duration_seconds
        if r.renotify_after_minutes:
            rule_entry["renotify_after_minutes"] = r.renotify_after_minutes
        if r.digest_minutes:
            rule_entry["digest_minutes"] = r.digest_minutes
        if not r.enabled:
            rule_entry["enabled"] = False
        rules_export.append(rule_entry)

    return {
        "version": "1",
        "exported_at": datetime.now(UTC).isoformat(),
        "groups": groups_export,
        "monitors": monitors_export,
        "alert_channels": channels_export,
        "alert_rules": rules_export,
    }


async def import_config(
    user: User,
    db: AsyncSession,
    config: dict[str, Any],
    dry_run: bool = False,
    prune: bool = True,
) -> dict[str, Any]:
    """Import a declarative config. Returns a plan of changes.

    Matching is by name (not UUID) for idempotence.
    """
    plan: dict[str, list] = {
        "groups_created": [],
        "groups_updated": [],
        "groups_deleted": [],
        "monitors_created": [],
        "monitors_updated": [],
        "monitors_deleted": [],
        "channels_created": [],
        "channels_updated": [],
        "channels_deleted": [],
        "rules_created": [],
        "rules_deleted": [],
    }

    # ── Groups ────────────────────────────────────────────────────────
    existing_groups = {
        g.name: g
        for g in (
            await db.execute(
                select(MonitorGroup).where(MonitorGroup.owner_id == user.id)
            )
        ).scalars().all()
    }

    config_group_names = set()
    group_name_to_id: dict[str, uuid.UUID] = {}

    for g_cfg in config.get("groups", []):
        name = g_cfg["name"]
        config_group_names.add(name)
        existing = existing_groups.get(name)

        if existing:
            changes = []
            for field in (
                "description", "public_slug", "custom_logo_url",
                "accent_color", "announcement_banner",
            ):
                new_val = g_cfg.get(field)
                if new_val != getattr(existing, field, None):
                    if not dry_run:
                        setattr(existing, field, new_val)
                    changes.append(field)
            if changes:
                plan["groups_updated"].append({"name": name, "changed_fields": changes})
            group_name_to_id[name] = existing.id
        else:
            plan["groups_created"].append({"name": name})
            if not dry_run:
                group = MonitorGroup(
                    name=name,
                    owner_id=user.id,
                    description=g_cfg.get("description"),
                    public_slug=g_cfg.get("public_slug"),
                    custom_logo_url=g_cfg.get("custom_logo_url"),
                    accent_color=g_cfg.get("accent_color"),
                    announcement_banner=g_cfg.get("announcement_banner"),
                    report_schedule=g_cfg.get("report_schedule"),
                    report_emails=g_cfg.get("report_emails"),
                )
                db.add(group)
                await db.flush()
                group_name_to_id[name] = group.id
            else:
                group_name_to_id[name] = uuid.uuid4()

    if prune:
        for name, group in existing_groups.items():
            if name not in config_group_names:
                plan["groups_deleted"].append({"name": name})
                if not dry_run:
                    await db.delete(group)

    # ── Alert channels ────────────────────────────────────────────────
    existing_channels = {
        c.name: c
        for c in (
            await db.execute(
                select(AlertChannel).where(AlertChannel.owner_id == user.id)
            )
        ).scalars().all()
    }

    config_channel_names = set()
    channel_name_to_id: dict[str, uuid.UUID] = {}

    for c_cfg in config.get("alert_channels", []):
        name = c_cfg["name"]
        config_channel_names.add(name)
        existing = existing_channels.get(name)

        if existing:
            channel_name_to_id[name] = existing.id
            changes = []
            if c_cfg.get("type") and c_cfg["type"] != existing.type.value:
                changes.append("type")
                if not dry_run:
                    existing.type = AlertChannelType(c_cfg["type"])
            # Only update config if non-redacted values provided
            new_config = c_cfg.get("config", {})
            if new_config and not _is_redacted(new_config):
                changes.append("config")
                if not dry_run:
                    existing.config = encrypt_channel_config(new_config)
            if changes:
                plan["channels_updated"].append({"name": name, "changed_fields": changes})
        else:
            plan["channels_created"].append({"name": name, "type": c_cfg.get("type", "email")})
            if not dry_run:
                channel = AlertChannel(
                    name=name,
                    owner_id=user.id,
                    type=AlertChannelType(c_cfg["type"]),
                    config=encrypt_channel_config(c_cfg.get("config", {})),
                )
                db.add(channel)
                await db.flush()
                channel_name_to_id[name] = channel.id
            else:
                channel_name_to_id[name] = uuid.uuid4()

    if prune:
        for name, channel in existing_channels.items():
            if name not in config_channel_names:
                plan["channels_deleted"].append({"name": name})
                if not dry_run:
                    await db.delete(channel)

    # ── Monitors ──────────────────────────────────────────────────────
    existing_monitors = {
        m.name: m
        for m in (
            await db.execute(
                select(Monitor).where(Monitor.owner_id == user.id)
            )
        ).scalars().all()
    }

    config_monitor_names = set()

    for m_cfg in config.get("monitors", []):
        name = m_cfg["name"]
        config_monitor_names.add(name)
        existing = existing_monitors.get(name)

        # Resolve group reference
        group_id = None
        if "group" in m_cfg:
            group_id = group_name_to_id.get(m_cfg["group"])

        if existing:
            changes = []
            for field in _MONITOR_EXPORT_FIELDS:
                if field == "name":
                    continue
                new_val = m_cfg.get(field)
                if new_val is not None and new_val != getattr(existing, field, None):
                    if not dry_run:
                        setattr(existing, field, new_val)
                    changes.append(field)
            if group_id and group_id != existing.group_id:
                if not dry_run:
                    existing.group_id = group_id
                changes.append("group")
            if changes:
                plan["monitors_updated"].append({"name": name, "changed_fields": changes})
        else:
            plan["monitors_created"].append({
                "name": name, "check_type": m_cfg.get("check_type", "http"),
            })
            if not dry_run:
                monitor_kwargs = {
                    "name": name,
                    "url": m_cfg.get("url", ""),
                    "owner_id": user.id,
                    "group_id": group_id,
                }
                for field in _MONITOR_EXPORT_FIELDS:
                    if field in ("name", "url"):
                        continue
                    if field in m_cfg:
                        monitor_kwargs[field] = m_cfg[field]
                monitor = Monitor(**monitor_kwargs)
                db.add(monitor)
                await db.flush()

    if prune:
        for name, monitor in existing_monitors.items():
            if name not in config_monitor_names:
                plan["monitors_deleted"].append({"name": name})
                if not dry_run:
                    await db.delete(monitor)

    # ── Alert rules ───────────────────────────────────────────────────
    # Rules are matched by (monitor_name, condition) or (group_name, condition)
    # For simplicity in v1, we delete all existing rules and recreate from config
    if config.get("alert_rules"):
        # Refresh monitor/group name maps after creates
        if not dry_run:
            await db.flush()
            all_monitors = {
                m.name: m.id
                for m in (
                    await db.execute(
                        select(Monitor).where(Monitor.owner_id == user.id)
                    )
                ).scalars().all()
            }
            all_groups = {
                g.name: g.id
                for g in (
                    await db.execute(
                        select(MonitorGroup).where(MonitorGroup.owner_id == user.id)
                    )
                ).scalars().all()
            }
        else:
            all_monitors = {m.name: m.id for m in existing_monitors.values()}
            all_groups = {g.name: g.id for g in existing_groups.values()}

        for r_cfg in config.get("alert_rules", []):
            target = r_cfg.get("monitor") or r_cfg.get("group", "?")
            rule_desc = f"{r_cfg.get('condition')} on {target}"
            plan["rules_created"].append({"description": rule_desc})
            if not dry_run:
                mon_name = r_cfg.get("monitor")
                monitor_id = all_monitors.get(mon_name) if mon_name else None
                group_id = all_groups.get(r_cfg.get("group")) if r_cfg.get("group") else None
                channel_ids = [
                    channel_name_to_id[cn]
                    for cn in r_cfg.get("channels", [])
                    if cn in channel_name_to_id
                ]
                if not channel_ids:
                    continue

                channels = (
                    await db.execute(
                        select(AlertChannel).where(AlertChannel.id.in_(channel_ids))
                    )
                ).scalars().all()

                rule = AlertRule(
                    owner_id=user.id,
                    monitor_id=monitor_id,
                    group_id=group_id,
                    condition=AlertCondition(r_cfg["condition"]),
                    channels=list(channels),
                    min_duration_seconds=r_cfg.get("min_duration_seconds", 0),
                    threshold_value=r_cfg.get("threshold_value"),
                    renotify_after_minutes=r_cfg.get("renotify_after_minutes"),
                    digest_minutes=r_cfg.get("digest_minutes", 0),
                    enabled=r_cfg.get("enabled", True),
                )
                db.add(rule)

    if not dry_run:
        await db.commit()

    # Summary
    total_changes = sum(len(v) for v in plan.values())
    plan["total_changes"] = total_changes
    plan["dry_run"] = dry_run

    return plan


# ── Helpers ───────────────────────────────────────────────────────────────────

_DEFAULTS = {
    "interval_seconds": 60,
    "timeout_seconds": 10,
    "follow_redirects": True,
    "expected_status_codes": [200],
    "enabled": True,
    "ssl_check_enabled": True,
    "ssl_expiry_warn_days": 30,
    "smtp_starttls": False,
    "domain_expiry_warn_days": 30,
    "keyword_negate": False,
    "schema_drift_enabled": False,
    "slo_window_days": 30,
    "network_scope": "all",
    "flap_threshold": 5,
    "flap_window_minutes": 10,
    "heartbeat_grace_seconds": 60,
    "dns_drift_alert": False,
    "dns_split_enabled": False,
}


def _get_default(field: str) -> Any:
    return _DEFAULTS.get(field)


def _redact_config(config: dict, channel_type: AlertChannelType) -> dict:
    """Redact secrets from channel config for export."""
    redacted = dict(config)
    secret_fields = {"bot_token", "secret", "webhook_secret", "integration_key", "api_key"}
    for key in secret_fields:
        if key in redacted:
            redacted[key] = "***"
    return redacted


def _is_redacted(config: dict) -> bool:
    """Check if a config dict contains only redacted values."""
    return all(v == "***" for v in config.values() if isinstance(v, str))
