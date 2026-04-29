"""Incident detection — multi-probe correlation logic with flapping detection."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
import structlog
from sqlalchemy import cast, func, or_, select
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from whatisup.core.database import dialect_name
from whatisup.models.alert import AlertCondition, AlertEvent, AlertEventStatus, AlertRule
from whatisup.models.incident import Incident, IncidentGroup, IncidentScope
from whatisup.models.monitor import Monitor, MonitorDependency
from whatisup.models.probe import Probe
from whatisup.models.result import CheckResult, CheckStatus
from whatisup.services.alert import dispatch_alert, maybe_digest_or_dispatch
from whatisup.services.anomaly import compute_zscore
from whatisup.services.correlation import update_patterns_for_group
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


async def _has_ancestor_incident(
    db: AsyncSession,
    monitor_id: uuid.UUID,
    visited: set[uuid.UUID] | None = None,
    depth: int = 0,
) -> bool:
    """Check if any ancestor in the dependency chain has an open incident.

    Follows the dependency graph recursively up to 5 hops to handle transitive
    suppression (e.g. A -> B -> C: if A is down, both B and C are suppressed).
    """
    if depth > 5:
        return False
    if visited is None:
        visited = set()
    if monitor_id in visited:
        return False
    visited.add(monitor_id)

    # Get direct parents with suppression enabled
    parents = (
        await db.execute(
            select(MonitorDependency).where(
                MonitorDependency.child_id == monitor_id,
                MonitorDependency.suppress_on_parent_down.is_(True),
            )
        )
    ).scalars().all()

    if not parents:
        return False

    for dep in parents:
        # Check if this parent has an open incident
        has_incident = (
            await db.execute(
                select(Incident.id).where(
                    Incident.monitor_id == dep.parent_id,
                    Incident.resolved_at.is_(None),
                ).limit(1)
            )
        ).scalar_one_or_none()

        if has_incident:
            return True

        # Recurse to grandparents
        if await _has_ancestor_incident(db, dep.parent_id, visited, depth + 1):
            return True

    return False


async def _is_suppressed_by_dependency(
    db: AsyncSession, monitor_id: uuid.UUID
) -> bool:
    """Return True if any ancestor monitor in the dependency chain has an open incident."""
    return await _has_ancestor_incident(db, monitor_id)


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
    # PostgreSQL: use JSONB ?| for efficient GIN-indexed overlap check
    # Fallback: Python-side filtering for non-PostgreSQL (tests use SQLite)
    base_query = select(Incident).where(
        Incident.resolved_at.is_(None),
        Incident.started_at >= window_start,
        Incident.monitor_id != monitor_id,
    )

    if dialect_name(db) == "postgresql":
        base_query = base_query.where(
            cast(Incident.affected_probe_ids, JSONB).op("?|")(
                cast(affected_probe_ids, ARRAY(sa.Text))
            )
        )
        correlated_incidents = (await db.execute(base_query)).scalars().all()
    else:
        # Fallback for SQLite (tests)
        open_incidents = (await db.execute(base_query)).scalars().all()
        probe_set = set(affected_probe_ids)
        correlated_incidents = [
            inc for inc in open_incidents
            if set(inc.affected_probe_ids) & probe_set
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
        # Identify root cause: the monitor whose incident started earliest
        all_incidents = [*correlated_incidents, incident]
        root_incident = min(all_incidents, key=lambda i: i.started_at)

        group = IncidentGroup(
            triggered_at=now,
            cause_probe_ids=list(set(affected_probe_ids)),
            status="open",
            root_cause_monitor_id=root_incident.monitor_id,
            correlation_type="probe",
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


async def _correlate_by_group(
    db: AsyncSession,
    incident: Incident,
    monitor: Monitor,
    publish_event,
) -> None:
    """
    If ≥50% of monitors in the same group went down within 2 minutes,
    create/join an IncidentGroup even without shared probe IDs.
    Detects shared infrastructure failures invisible to probe-level correlation.
    """
    if not monitor.group_id or incident.group_id is not None:
        return

    window_start = datetime.now(UTC) - timedelta(minutes=2)

    # Count enabled monitors in this group
    group_monitors = (
        await db.execute(
            select(Monitor.id).where(
                Monitor.group_id == monitor.group_id,
                Monitor.enabled.is_(True),
            )
        )
    ).scalars().all()

    if len(group_monitors) < 2:
        return

    # Find open incidents from the same group started recently
    sibling_incidents = (
        (
            await db.execute(
                select(Incident).where(
                    Incident.monitor_id.in_(group_monitors),
                    Incident.monitor_id != monitor.id,
                    Incident.resolved_at.is_(None),
                    Incident.started_at >= window_start,
                )
            )
        )
        .scalars()
        .all()
    )

    # Need ≥50% of group monitors to be down (including the current one)
    down_count = len(sibling_incidents) + 1  # +1 for current incident
    threshold = len(group_monitors) / 2
    if down_count < threshold:
        return

    # Check if any sibling is already in a group
    existing_group_id = next(
        (inc.group_id for inc in sibling_incidents if inc.group_id is not None),
        None,
    )

    now = datetime.now(UTC)
    group: IncidentGroup | None = None

    if existing_group_id:
        group = await db.get(IncidentGroup, existing_group_id)

    if group is None:
        all_incidents = [*sibling_incidents, incident]
        root_incident = min(all_incidents, key=lambda i: i.started_at)

        group = IncidentGroup(
            triggered_at=now,
            cause_probe_ids=[],
            status="open",
            root_cause_monitor_id=root_incident.monitor_id,
            correlation_type="group",
        )
        db.add(group)
        await db.flush()
        for inc in sibling_incidents:
            if inc.group_id is None:
                inc.group_id = group.id

    incident.group_id = group.id
    await db.flush()

    correlated_monitor_ids = [str(inc.monitor_id) for inc in sibling_incidents]
    logger.info(
        "group_correlation_detected",
        monitor_id=str(monitor.id),
        group_id=str(group.id),
        down_count=down_count,
        group_size=len(group_monitors),
    )
    await publish_event(
        {
            "type": "common_cause_detected",
            "group_id": str(group.id),
            "monitor_id": str(monitor.id),
            "correlated_monitor_ids": correlated_monitor_ids,
            "correlation_type": "group",
        }
    )


async def _correlate_by_dependency(
    db: AsyncSession,
    incident: Incident,
    monitor_id: uuid.UUID,
    publish_event,
) -> None:
    """
    Cascade correlation: if a parent and its children go down within 5 minutes,
    group them together using existing MonitorDependency edges.
    """
    if incident.group_id is not None:
        return

    window_start = datetime.now(UTC) - timedelta(minutes=5)
    now = datetime.now(UTC)

    # Find parent monitors for the current monitor
    parent_deps = (
        await db.execute(
            select(MonitorDependency.parent_id).where(
                MonitorDependency.child_id == monitor_id
            )
        )
    ).scalars().all()

    # Find child monitors for the current monitor
    child_deps = (
        await db.execute(
            select(MonitorDependency.child_id).where(
                MonitorDependency.parent_id == monitor_id
            )
        )
    ).scalars().all()

    related_ids = list(set(parent_deps) | set(child_deps))
    if not related_ids:
        return

    # Find open incidents on related monitors within the cascade window
    related_incidents = (
        (
            await db.execute(
                select(Incident).where(
                    Incident.monitor_id.in_(related_ids),
                    Incident.resolved_at.is_(None),
                    Incident.started_at >= window_start,
                )
            )
        )
        .scalars()
        .all()
    )

    if not related_incidents:
        return

    # Check if any related incident is already in a group
    existing_group_id = next(
        (inc.group_id for inc in related_incidents if inc.group_id is not None),
        None,
    )

    group: IncidentGroup | None = None
    if existing_group_id:
        group = await db.get(IncidentGroup, existing_group_id)
        if group and incident.group_id is None:
            incident.group_id = group.id

    if group is None:
        all_incidents = [*related_incidents, incident]
        root_incident = min(all_incidents, key=lambda i: i.started_at)

        group = IncidentGroup(
            triggered_at=now,
            cause_probe_ids=[],
            status="open",
            root_cause_monitor_id=root_incident.monitor_id,
            correlation_type="dependency",
        )
        db.add(group)
        await db.flush()
        for inc in related_incidents:
            if inc.group_id is None:
                inc.group_id = group.id
        incident.group_id = group.id

    await db.flush()

    logger.info(
        "dependency_cascade_detected",
        monitor_id=str(monitor_id),
        group_id=str(group.id),
        related_monitors=[str(inc.monitor_id) for inc in related_incidents],
    )
    await publish_event(
        {
            "type": "common_cause_detected",
            "group_id": str(group.id),
            "monitor_id": str(monitor_id),
            "correlated_monitor_ids": [str(inc.monitor_id) for inc in related_incidents],
            "correlation_type": "dependency",
        }
    )


async def _fire_alerts(
    db: AsyncSession,
    incident: Incident,
    monitor: Monitor,
    result: CheckResult | None = None,
    event_type: str = "incident_opened",
    extra_ctx: dict | None = None,
) -> None:
    """Evaluate alert rules for this monitor/group and dispatch matching ones.

    event_type values:
      - "incident_opened": new incident just opened
      - "incident_resolved": incident just resolved
      - "incident_renotify": incident still open, check for periodic re-notification
    """
    # Collect applicable rules (by monitor, group, or tag selector intersecting monitor tags)
    conditions = [AlertRule.monitor_id == monitor.id]
    if monitor.group_id:
        conditions.append(AlertRule.group_id == monitor.group_id)
    conditions.append(AlertRule.tag_selector.isnot(None))

    candidate_rules = (
        (
            await db.execute(
                select(AlertRule).where(or_(*conditions)).options(selectinload(AlertRule.channels))
            )
        )
        .scalars()
        .all()
    )

    monitor_tag_names = {t.name for t in (monitor.tags or [])}
    rules = [
        r for r in candidate_rules
        if r.monitor_id == monitor.id
        or (monitor.group_id is not None and r.group_id == monitor.group_id)
        or (r.tag_selector and monitor_tag_names.intersection(r.tag_selector))
    ]

    # Web push: notify monitor owner for open/resolve events (independent of rules)
    if event_type in ("incident_opened", "incident_resolved"):
        from whatisup.services.web_push import dispatch_web_push_for_incident
        await dispatch_web_push_for_incident(db, incident, monitor, event_type)

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

    ctx: dict = {
        "monitor_name": monitor.name,
        "monitor_url": monitor.url,
        "check_type": monitor.check_type,
        "probe_names": probe_names,
        **(extra_ctx or {}),
    }

    now = datetime.now(UTC)

    for rule in rules:
        # Skip disabled rules
        if not rule.enabled:
            continue

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
            # Skip renotify if incident has been acknowledged
            if incident.acked_at is not None:
                continue
            # T1-04: skip renotify while a snooze window is still active. Once
            # snooze_until is in the past the next cycle picks the incident up.
            if incident.snooze_until is not None and incident.snooze_until > now:
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
                            AlertEvent.incident_id == incident.id,
                            AlertEvent.status == AlertEventStatus.sent,
                            AlertEvent.sent_at >= storm_cutoff,
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

        elif rule.condition == AlertCondition.anomaly_detection:
            if event_type != "incident_opened":
                continue
            if result.response_time_ms is None:
                continue
            # zscore is pre-computed by process_check_result and injected into ctx
            zscore = ctx.get("zscore")
            if zscore is None:
                continue
            threshold = rule.anomaly_zscore_threshold or 3.0
            if zscore <= threshold:
                continue
            ctx = {**ctx, "response_time_ms": result.response_time_ms}

        elif rule.condition == AlertCondition.schema_drift:
            if event_type != "incident_opened":
                continue
            # schema_drift fires when the fingerprint differs from the stored baseline
            if not result.schema_fingerprint:
                continue
            if not monitor.schema_baseline:
                continue  # No baseline set yet → no alert
            if result.schema_fingerprint == monitor.schema_baseline:
                continue  # No change
            ctx = {
                **ctx,
                "schema_fingerprint": result.schema_fingerprint,
                "schema_baseline": monitor.schema_baseline,
            }

        for channel in rule.channels:
            await maybe_digest_or_dispatch(db, incident, channel, rule, event_type, ctx=ctx)

    await db.flush()


async def _process_composite_result(
    db: AsyncSession,
    result: CheckResult,
    monitor: Monitor,
    publish_event,
) -> None:
    """
    Simplified incident lifecycle for composite monitors.
    No multi-probe logic — composite state is already aggregated by services/composite.py.
    """
    monitor_id = result.monitor_id
    is_down = result.status in (CheckStatus.down, CheckStatus.timeout, CheckStatus.error)
    scope = IncidentScope.global_ if is_down else None

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
        incident = Incident(
            monitor_id=monitor_id,
            started_at=now,
            scope=scope,
            affected_probe_ids=[],
            first_failure_at=result.checked_at if result else now,
        )
        db.add(incident)
        try:
            await db.flush()
        except IntegrityError:
            await db.rollback()
            logger.info("composite_incident_deduplicated", monitor_id=str(monitor_id))
            return
        logger.info("composite_incident_opened", monitor_id=str(monitor_id))
        await publish_event(
            {
                "type": "incident_opened",
                "monitor_id": str(monitor_id),
                "incident_id": str(incident.id),
                "scope": scope.value,
                "affected_probes": [],
                "started_at": now.isoformat(),
                "dependency_suppressed": False,
            }
        )
        await _fire_alerts(db, incident, monitor, result, "incident_opened")

    elif scope is None and open_incident is not None:
        duration = int((now - open_incident.started_at).total_seconds())
        open_incident.resolved_at = now
        open_incident.duration_seconds = duration
        await db.flush()
        logger.info(
            "composite_incident_resolved",
            monitor_id=str(monitor_id),
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
        await _fire_alerts(db, open_incident, monitor, result, "incident_resolved")


async def _create_point_in_time_incident(
    db: AsyncSession,
    monitor_id: uuid.UUID,
    monitor: Monitor,
    result: CheckResult,
    extra_ctx: dict | None = None,
) -> None:
    """Create a resolved point-in-time incident (duration=0) for synthetic alerts
    such as schema drift and anomaly detection, then fire alert rules."""
    now = datetime.now(UTC)
    incident = Incident(
        monitor_id=monitor_id,
        started_at=now,
        scope=IncidentScope.global_,
        affected_probe_ids=[str(result.probe_id)] if result.probe_id else [],
        resolved_at=now,
        duration_seconds=0,
    )
    db.add(incident)
    await db.flush()
    await _fire_alerts(db, incident, monitor, result, "incident_opened", extra_ctx=extra_ctx)


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

    # Composite monitor — skip multi-probe logic, use simplified path
    if monitor and monitor.check_type == "composite":
        await _process_composite_result(db, result, monitor, publish_event)
        return

    group_id = monitor.group_id if monitor else None

    in_maintenance = await is_in_maintenance(db, monitor_id, group_id)
    if in_maintenance:
        # Create a suppressed incident for audit trail if result is down
        if result.status in (CheckStatus.down, CheckStatus.timeout, CheckStatus.error):
            _existing = (
                await db.execute(
                    select(Incident).where(
                        Incident.monitor_id == monitor_id,
                        Incident.resolved_at.is_(None),
                    )
                )
            ).scalar_one_or_none()
            if _existing is None:
                _maint_incident = Incident(
                    monitor_id=monitor_id,
                    started_at=result.checked_at,
                    scope=IncidentScope.global_,
                    affected_probe_ids=[str(result.probe_id)] if result.probe_id else [],
                    dependency_suppressed=True,
                )
                db.add(_maint_incident)
                await db.flush()
                logger.info(
                    "incident_created_maintenance_suppressed",
                    monitor_id=str(monitor_id),
                    incident_id=str(_maint_incident.id),
                )
        else:
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
            first_failure_at=result.checked_at if result else now,
        )
        db.add(incident)
        try:
            await db.flush()
        except IntegrityError:
            # Race condition: another request already created an open incident
            await db.rollback()
            logger.info("incident_creation_deduplicated", monitor_id=str(monitor_id))
            return

        # V2-02-02 — classify network verdict using the latest_by_probe map we
        # already loaded. Best-effort: any failure leaves verdict null and is
        # logged. The background task will retry every 5 min while open.
        try:
            from whatisup.services.network_verdict import classify_network_verdict

            await classify_network_verdict(
                db, incident, latest_by_probe=latest_by_probe, persist=True
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "network_verdict_initial_failed",
                incident_id=str(incident.id),
                error_type=type(exc).__name__,
                error=str(exc),
            )

        logger.info(
            "incident_opened",
            monitor_id=str(monitor_id),
            scope=scope.value,
            probes_down=probes_down,
            probes_total=probes_total,
            dependency_suppressed=suppressed,
            network_verdict=incident.network_verdict,
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

            # B2: If probe correlation didn't group it, try group-level correlation
            if incident.group_id is None:
                await _correlate_by_group(db, incident, monitor, publish_event)

            # B3: If still ungrouped, try dependency cascade correlation (5min window)
            if incident.group_id is None:
                await _correlate_by_dependency(db, incident, monitor_id, publish_event)

            # B4: Update co-occurrence patterns when an incident is grouped
            # Deferred to a background task to avoid O(n^2) upserts in the
            # critical incident pipeline path.
            if incident.group_id is not None:
                _group_id = incident.group_id

                async def _deferred_pattern_update() -> None:
                    from whatisup.core.database import get_session_factory

                    try:
                        async with get_session_factory()() as bg_db:
                            grp = await bg_db.get(IncidentGroup, _group_id)
                            if grp:
                                await update_patterns_for_group(bg_db, grp)
                            await bg_db.commit()
                    except Exception:
                        logger.exception(
                            "deferred_pattern_update_failed",
                            group_id=str(_group_id),
                        )

                def _log_task_exception(t):
                    if t.cancelled():
                        return
                    exc = t.exception()
                    if exc:
                        logger.error("deferred_pattern_update_task_failed", error=str(exc))

                _task = asyncio.create_task(_deferred_pattern_update())
                _task.add_done_callback(_log_task_exception)

            # Fire alert for this incident — enriched with group context if correlated
            extra_ctx = None
            if incident.group_id is not None:
                extra_ctx = {"correlated_group_id": str(incident.group_id)}
            await _fire_alerts(
                db, incident, monitor, result, "incident_opened", extra_ctx=extra_ctx
            )
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
        # Resolve incident — clear ack on state change
        duration = int((now - open_incident.started_at).total_seconds())
        open_incident.resolved_at = now
        open_incident.duration_seconds = duration
        open_incident.acked_at = None
        open_incident.acked_by_id = None
        open_incident.snooze_until = None  # T1-04: clear snooze on resolve
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

    # Propagate state change to any composite monitors that include this monitor
    # (skip if this monitor itself is composite to avoid infinite recursion)
    if monitor and monitor.check_type != "composite":
        from whatisup.services.composite import evaluate_composite_parents

        await evaluate_composite_parents(db, monitor_id, publish_event)

    # Schema drift detection — update baseline on first result, fire alerts on change
    if (
        monitor
        and monitor.schema_drift_enabled
        and result.schema_fingerprint
        and result.status == CheckStatus.up
    ):
        if not monitor.schema_baseline:
            # Set initial baseline silently
            monitor.schema_baseline = result.schema_fingerprint
            monitor.schema_baseline_updated_at = datetime.now(UTC)
            logger.info("schema_baseline_set", monitor_id=str(monitor_id))
        elif result.schema_fingerprint != monitor.schema_baseline:
            logger.info(
                "schema_drift_detected",
                monitor_id=str(monitor_id),
                old=monitor.schema_baseline,
                new=result.schema_fingerprint,
            )
            await _create_point_in_time_incident(db, monitor_id, monitor, result)

    # Anomaly detection — fire point-in-time alerts when z-score threshold exceeded
    if (
        monitor
        and result.status == CheckStatus.up
        and result.response_time_ms is not None
    ):
        # Check if any anomaly_detection rules exist for this monitor before doing z-score
        anomaly_conditions = [AlertRule.monitor_id == monitor.id]
        if monitor.group_id:
            anomaly_conditions.append(AlertRule.group_id == monitor.group_id)
        has_anomaly_rule = (
            await db.execute(
                select(AlertRule.id)
                .where(
                    or_(*anomaly_conditions),
                    AlertRule.condition == AlertCondition.anomaly_detection,
                    AlertRule.enabled.is_(True),
                )
                .limit(1)
            )
        ).scalar_one_or_none()

        if has_anomaly_rule:
            # Compute z-score once; _fire_alerts will check per-rule threshold from ctx
            zscore = await compute_zscore(db, monitor_id, result.response_time_ms)
            if zscore is not None:
                logger.info(
                    "anomaly_zscore_computed",
                    monitor_id=str(monitor_id),
                    response_time_ms=result.response_time_ms,
                    zscore=zscore,
                )
                await _create_point_in_time_incident(
                    db, monitor_id, monitor, result, extra_ctx={"zscore": zscore}
                )

    # Auto-pause: if monitor.auto_pause_after is set, check last N results
    if monitor and monitor.auto_pause_after and monitor.enabled:
        last_n = (
            await db.execute(
                select(CheckResult.status)
                .where(CheckResult.monitor_id == monitor.id)
                .order_by(CheckResult.checked_at.desc())
                .limit(monitor.auto_pause_after)
            )
        ).scalars().all()
        if (
            len(last_n) >= monitor.auto_pause_after
            and all(s != CheckStatus.up for s in last_n)
        ):
            monitor.enabled = False
            logger.warning(
                "auto_pause_triggered",
                monitor_id=str(monitor.id),
                consecutive_failures=len(last_n),
            )
