"""Incident detection — multi-probe correlation logic with flapping detection."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from whatisup.models.alert import AlertCondition, AlertEvent, AlertEventStatus, AlertRule
from whatisup.models.incident import Incident, IncidentGroup, IncidentScope
from whatisup.models.monitor import Monitor, MonitorDependency
from whatisup.models.probe import Probe
from whatisup.models.result import CheckResult, CheckStatus
from whatisup.services.alert import dispatch_alert, maybe_digest_or_dispatch
from whatisup.services.maintenance import is_group_maintenance_suppressed, is_in_maintenance
from whatisup.services.stats import invalidate_uptime_cache, latest_results_subq

logger = structlog.get_logger(__name__)

# Global defaults — overridden per-monitor by flap_threshold / flap_window_minutes
_DEFAULT_FLAP_THRESHOLD = 5
_DEFAULT_FLAP_WINDOW_MINUTES = 10


async def _is_flapping(db: AsyncSession, monitor: Monitor) -> bool:
    """Detect rapid up/down oscillation within the monitor's flap window."""
    threshold = monitor.flap_threshold or _DEFAULT_FLAP_THRESHOLD
    window = monitor.flap_window_minutes or _DEFAULT_FLAP_WINDOW_MINUTES
    cutoff = datetime.now(UTC) - timedelta(minutes=window)
    rows = (
        await db.execute(
            select(CheckResult.status, CheckResult.checked_at)
            .where(
                CheckResult.monitor_id == monitor.id,
                CheckResult.checked_at >= cutoff,
            )
            .order_by(CheckResult.checked_at.asc())
        )
    ).all()

    if len(rows) < threshold:
        return False

    transitions = sum(
        1
        for i in range(1, len(rows))
        if (rows[i].status == CheckStatus.up) != (rows[i - 1].status == CheckStatus.up)
    )
    return transitions >= threshold


async def _is_suppressed_by_dependency(
    db: AsyncSession, monitor_id: uuid.UUID
) -> bool:
    """Return True if any active parent monitor has an open incident with suppress enabled."""
    deps = (
        await db.execute(
            select(MonitorDependency).where(
                MonitorDependency.child_id == monitor_id,
                MonitorDependency.suppress_on_parent_down.is_(True),
            )
        )
    ).scalars().all()

    if not deps:
        return False

    parent_ids = [d.parent_id for d in deps]
    open_parent = (
        await db.execute(
            select(Incident.id).where(
                Incident.monitor_id.in_(parent_ids),
                Incident.resolved_at.is_(None),
            ).limit(1)
        )
    ).scalar_one_or_none()

    return open_parent is not None


async def _correlate_common_cause(
    db: AsyncSession,
    incident: Incident,
    affected_probe_ids: list[str],
    publish_event,
) -> None:
    """
    If multiple monitors became down at the same time via the same probes,
    persist a correlation group and emit a WebSocket event.
    """
    if not affected_probe_ids:
        return

    monitor_id = incident.monitor_id
    window_start = datetime.now(UTC) - timedelta(seconds=90)

    # Find open incidents started recently with overlapping affected probes
    open_incidents = (
        (
            await db.execute(
                select(Incident).where(
                    Incident.resolved_at.is_(None),
                    Incident.started_at >= window_start,
                    Incident.monitor_id != monitor_id,
                )
            )
        )
        .scalars()
        .all()
    )

    correlated_incidents = [
        inc for inc in open_incidents
        if set(inc.affected_probe_ids) & set(affected_probe_ids)
    ]

    if not correlated_incidents:
        return

    # Find if any correlated incident already belongs to a group
    existing_group_id: uuid.UUID | None = next(
        (inc.group_id for inc in correlated_incidents if inc.group_id is not None),
        None,
    )

    now = datetime.now(UTC)

    group: IncidentGroup | None = None
    if existing_group_id:
        group = await db.get(IncidentGroup, existing_group_id)
        if group:
            # Merge probe IDs
            merged = list(set(group.cause_probe_ids) | set(affected_probe_ids))
            group.cause_probe_ids = merged

    if group is None:
        group = IncidentGroup(
            triggered_at=now,
            cause_probe_ids=list(set(affected_probe_ids)),
            status="open",
        )
        db.add(group)
        await db.flush()  # generate group.id
        # Attach all correlated incidents to the new group
        for inc in correlated_incidents:
            if inc.group_id is None:
                inc.group_id = group.id

    # Attach the new incident to the group
    incident.group_id = group.id
    await db.flush()

    correlated_monitor_ids = [str(inc.monitor_id) for inc in correlated_incidents]
    logger.info(
        "common_cause_detected",
        monitor_id=str(monitor_id),
        group_id=str(group.id),
        correlated_monitors=correlated_monitor_ids,
        shared_probes=affected_probe_ids,
    )
    await publish_event(
        {
            "type": "common_cause_detected",
            "group_id": str(group.id),
            "monitor_id": str(monitor_id),
            "correlated_monitor_ids": correlated_monitor_ids,
            "shared_probe_ids": affected_probe_ids,
        }
    )


async def _fire_alerts(
    db: AsyncSession,
    incident: Incident,
    monitor: Monitor,
    result: CheckResult,
    event_type: str,
) -> None:
    """Evaluate alert rules for this monitor/group and dispatch matching ones.

    event_type values:
      - "incident_opened": new incident just opened
      - "incident_resolved": incident just resolved
      - "incident_renotify": incident still open, check for periodic re-notification
    """
    # Collect applicable rules (by monitor or by group)
    conditions = [AlertRule.monitor_id == monitor.id]
    if monitor.group_id:
        conditions.append(AlertRule.group_id == monitor.group_id)

    rules = (
        (
            await db.execute(
                select(AlertRule).where(or_(*conditions)).options(selectinload(AlertRule.channels))
            )
        )
        .scalars()
        .all()
    )

    if not rules:
        return

    # Resolve probe names for enriched context
    probe_names: dict[str, str] = {}
    if incident.affected_probe_ids:
        probe_uuids = []
        for pid in incident.affected_probe_ids:
            try:
                probe_uuids.append(uuid.UUID(pid))
            except ValueError:
                pass
        if probe_uuids:
            probes = (
                (await db.execute(select(Probe).where(Probe.id.in_(probe_uuids)))).scalars().all()
            )
            probe_names = {str(p.id): p.name for p in probes}

    ctx = {
        "monitor_name": monitor.name,
        "check_type": monitor.check_type,
        "probe_names": probe_names,
    }

    now = datetime.now(UTC)

    for rule in rules:
        # H-10: min_duration_seconds — skip if incident too short for "opened" events
        if (
            event_type == "incident_opened"
            and rule.min_duration_seconds > 0
            and (now - incident.started_at).total_seconds() < rule.min_duration_seconds
        ):
            continue

        # H-11: renotify logic — only fire for renotify events if rule allows it
        if event_type == "incident_renotify":
            if not rule.renotify_after_minutes:
                continue
            # Only applicable for down-type conditions
            if rule.condition not in (AlertCondition.any_down, AlertCondition.all_down):
                continue
            # Check last sent alert event for this incident + rule channels
            channel_ids = [c.id for c in rule.channels]
            if channel_ids:
                last_event = (
                    await db.execute(
                        select(AlertEvent)
                        .where(
                            AlertEvent.incident_id == incident.id,
                            AlertEvent.channel_id.in_(channel_ids),
                            AlertEvent.status == AlertEventStatus.sent,
                        )
                        .order_by(AlertEvent.sent_at.desc())
                        .limit(1)
                    )
                ).scalar_one_or_none()
                if last_event:
                    minutes_since = (now - last_event.sent_at).total_seconds() / 60
                    if minutes_since < rule.renotify_after_minutes:
                        continue
            # Dispatch renotify directly (digest ne s'applique pas au renotify)
            for channel in rule.channels:
                await dispatch_alert(db, incident, channel, "incident_opened", ctx=ctx)
            continue

        # Storm protection: skip if too many alerts sent recently for this rule
        if (
            rule.storm_window_seconds
            and rule.storm_max_alerts
            and event_type == "incident_opened"
        ):
            storm_cutoff = now - timedelta(seconds=rule.storm_window_seconds)
            channel_ids = [c.id for c in rule.channels]
            if channel_ids:
                recent_count = (
                    await db.execute(
                        select(func.count(AlertEvent.id)).where(
                            AlertEvent.channel_id.in_(channel_ids),
                            AlertEvent.sent_at >= storm_cutoff,
                            AlertEvent.status == AlertEventStatus.sent,
                        )
                    )
                ).scalar_one()
                if recent_count >= rule.storm_max_alerts:
                    logger.info(
                        "alert_storm_throttled",
                        rule_id=str(rule.id),
                        recent_count=recent_count,
                        storm_max=rule.storm_max_alerts,
                    )
                    continue

        # Standard condition evaluation for opened/resolved
        if rule.condition == AlertCondition.any_down:
            if event_type not in ("incident_opened", "incident_resolved"):
                continue
        elif rule.condition == AlertCondition.all_down:
            if incident.scope != IncidentScope.global_ and event_type == "incident_opened":
                continue
            if event_type not in ("incident_opened", "incident_resolved"):
                continue
        elif rule.condition == AlertCondition.ssl_expiry:
            if not (
                result.ssl_valid is False
                or (
                    result.ssl_days_remaining is not None
                    and monitor.ssl_expiry_warn_days is not None
                    and result.ssl_days_remaining <= monitor.ssl_expiry_warn_days
                )
            ):
                continue
            if event_type != "incident_opened":
                continue
        elif rule.condition == AlertCondition.response_time_above:
            if rule.threshold_value is None:
                continue
            if result.response_time_ms is None or result.response_time_ms <= rule.threshold_value:
                continue
            if event_type != "incident_opened":
                continue
        elif rule.condition == AlertCondition.uptime_below:
            if event_type != "incident_opened":
                continue
        elif rule.condition == AlertCondition.response_time_above_baseline:
            if event_type != "incident_opened":
                continue
            if rule.baseline_factor is None or result.response_time_ms is None:
                continue
            # Compute 7-day rolling average for the same hour-of-week
            baseline_cutoff = now - timedelta(days=7)
            baseline_row = (
                await db.execute(
                    select(func.avg(CheckResult.response_time_ms)).where(
                        CheckResult.monitor_id == monitor.id,
                        CheckResult.checked_at >= baseline_cutoff,
                        CheckResult.response_time_ms.isnot(None),
                    )
                )
            ).scalar_one_or_none()
            if not baseline_row or baseline_row <= 0:
                continue
            if result.response_time_ms <= baseline_row * rule.baseline_factor:
                continue

        for channel in rule.channels:
            await maybe_digest_or_dispatch(db, incident, channel, rule, event_type, ctx=ctx)

    await db.flush()


async def process_check_result(
    db: AsyncSession,
    result: CheckResult,
    publish_event,
) -> None:
    """
    Called after a new CheckResult is stored.
    Performs multi-probe correlation, flapping detection, and incident lifecycle management.
    """
    monitor_id = result.monitor_id

    # Check maintenance window — suppress incident creation if in maintenance
    monitor = (
        await db.execute(select(Monitor).where(Monitor.id == monitor_id))
    ).scalar_one_or_none()
    group_id = monitor.group_id if monitor else None

    in_maintenance = await is_in_maintenance(db, monitor_id, group_id)
    if in_maintenance:
        logger.info("check_suppressed_maintenance", monitor_id=str(monitor_id))
        return

    # Item 7: group-level maintenance suppression when all monitors in group are down
    if group_id is not None:
        group_maintenance = await is_group_maintenance_suppressed(db, group_id)
        if group_maintenance:
            # Check if all other monitors in the group are also down
            from whatisup.models.incident import Incident as _Incident
            from whatisup.models.monitor import Monitor as _Monitor
            all_in_group = (
                await db.execute(
                    select(_Monitor.id).where(
                        _Monitor.group_id == group_id,
                        _Monitor.enabled.is_(True),
                    )
                )
            ).scalars().all()
            if all_in_group:
                open_incidents_count = (
                    await db.execute(
                        select(func.count(_Incident.id)).where(
                            _Incident.monitor_id.in_(all_in_group),
                            _Incident.resolved_at.is_(None),
                        )
                    )
                ).scalar_one()
                # All monitors in group are down (open incident count == group size or close)
                if open_incidents_count >= len(all_in_group) - 1:
                    logger.info(
                        "check_suppressed_group_maintenance",
                        monitor_id=str(monitor_id),
                        group_id=str(group_id),
                    )
                    return

    # Invalidate uptime cache — a new result arrived, cached stats are stale
    await invalidate_uptime_cache(monitor_id)

    # Fetch all active probes
    active_probes = (await db.execute(select(Probe).where(Probe.is_active))).scalars().all()

    if not active_probes:
        return

    active_probe_ids = {p.id for p in active_probes}

    # Batch query: latest result per probe for this monitor (replaces N individual queries)
    latest_subq = latest_results_subq(
        CheckResult.monitor_id == monitor_id,
        group_col=CheckResult.probe_id,
    )
    batch_results = (
        (
            await db.execute(
                select(CheckResult)
                .join(
                    latest_subq,
                    (CheckResult.probe_id == latest_subq.c.probe_id)
                    & (CheckResult.checked_at == latest_subq.c.max_at),
                )
                .where(CheckResult.monitor_id == monitor_id)
            )
        )
        .scalars()
        .all()
    )

    latest_by_probe: dict[uuid.UUID, CheckResult] = {
        r.probe_id: r for r in batch_results if r.probe_id in active_probe_ids
    }

    if not latest_by_probe:
        return

    probes_total = len(latest_by_probe)
    probes_down = sum(
        1
        for r in latest_by_probe.values()
        if r.status in (CheckStatus.down, CheckStatus.timeout, CheckStatus.error)
    )
    affected_probe_ids = [
        str(pid)
        for pid, r in latest_by_probe.items()
        if r.status in (CheckStatus.down, CheckStatus.timeout, CheckStatus.error)
    ]

    # Determine scope
    if probes_down == 0:
        scope = None
    elif probes_down == probes_total:
        scope = IncidentScope.global_
    else:
        scope = IncidentScope.geographic

    # Flapping detection — don't open new incidents if flapping
    if scope is not None:
        flapping = await _is_flapping(db, monitor)
        if flapping:
            logger.info(
                "flapping_detected",
                monitor_id=str(monitor_id),
                probes_down=probes_down,
            )
            await publish_event(
                {
                    "type": "flapping_detected",
                    "monitor_id": str(monitor_id),
                    "probes_down": probes_down,
                    "probes_total": probes_total,
                }
            )
            return

    # Fetch open incident for this monitor
    open_incident = (
        await db.execute(
            select(Incident).where(
                Incident.monitor_id == monitor_id,
                Incident.resolved_at.is_(None),
            )
        )
    ).scalar_one_or_none()

    now = datetime.now(UTC)

    if scope is not None and open_incident is None:
        # Check if a parent monitor is down — suppress alerts if so
        suppressed = await _is_suppressed_by_dependency(db, monitor_id)

        # Open a new incident (still created for tracking, even if suppressed)
        incident = Incident(
            monitor_id=monitor_id,
            started_at=now,
            scope=scope,
            affected_probe_ids=affected_probe_ids,
            dependency_suppressed=suppressed,
        )
        db.add(incident)
        await db.flush()

        logger.info(
            "incident_opened",
            monitor_id=str(monitor_id),
            scope=scope.value,
            probes_down=probes_down,
            probes_total=probes_total,
            dependency_suppressed=suppressed,
        )

        await publish_event(
            {
                "type": "incident_opened",
                "monitor_id": str(monitor_id),
                "incident_id": str(incident.id),
                "scope": scope.value,
                "affected_probes": affected_probe_ids,
                "started_at": now.isoformat(),
                "dependency_suppressed": suppressed,
            }
        )

        # Fire alerts only when not suppressed by a parent dependency
        if not suppressed:
            # Detect common cause and group the incident BEFORE firing alerts,
            # so grouped incidents skip individual notifications.
            await _correlate_common_cause(db, incident, affected_probe_ids, publish_event)

            # Only fire individual alert if NOT part of a group that already notified
            if incident.group_id is None:
                await _fire_alerts(db, incident, monitor, result, "incident_opened")
        else:
            logger.info(
                "incident_alerts_suppressed_by_dependency",
                monitor_id=str(monitor_id),
                incident_id=str(incident.id),
            )

    elif scope is not None and open_incident is not None:
        # Update scope/affected probes if changed
        if open_incident.scope != scope or set(open_incident.affected_probe_ids) != set(
            affected_probe_ids
        ):
            open_incident.scope = scope
            open_incident.affected_probe_ids = affected_probe_ids

        # H-11: fire renotify alerts — only load rules if any have renotify configured
        # to avoid a DB query on every check result when no rules use this feature
        renotify_conditions = [AlertRule.monitor_id == monitor.id]
        if monitor.group_id:
            renotify_conditions.append(AlertRule.group_id == monitor.group_id)
        has_renotify = (
            await db.execute(
                select(AlertRule.id)
                .where(
                    or_(*renotify_conditions),
                    AlertRule.renotify_after_minutes.isnot(None),
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if has_renotify:
            await _fire_alerts(db, open_incident, monitor, result, "incident_renotify")

    elif scope is None and open_incident is not None:
        # Resolve incident
        duration = int((now - open_incident.started_at).total_seconds())
        open_incident.resolved_at = now
        open_incident.duration_seconds = duration
        await db.flush()

        logger.info(
            "incident_resolved",
            monitor_id=str(monitor_id),
            incident_id=str(open_incident.id),
            duration_seconds=duration,
        )

        await publish_event(
            {
                "type": "incident_resolved",
                "monitor_id": str(monitor_id),
                "incident_id": str(open_incident.id),
                "duration_seconds": duration,
                "resolved_at": now.isoformat(),
            }
        )

        # Fire resolve alerts only when incident was not suppressed
        if not open_incident.dependency_suppressed:
            await _fire_alerts(db, open_incident, monitor, result, "incident_resolved")

        # Auto-resolve the group when all its incidents are resolved
        if open_incident.group_id is not None:
            group = await db.get(IncidentGroup, open_incident.group_id)
            if group and group.status == "open":
                siblings = (
                    await db.execute(
                        select(Incident).where(
                            Incident.group_id == group.id,
                            Incident.resolved_at.is_(None),
                        ).limit(1)
                    )
                ).scalar_one_or_none()
                if siblings is None:
                    # All incidents in group are resolved
                    group.status = "resolved"
                    group.resolved_at = now
                    logger.info("incident_group_resolved", group_id=str(group.id))
