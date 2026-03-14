"""Incident detection — multi-probe correlation logic with flapping detection."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from whatisup.models.alert import AlertCondition, AlertEvent, AlertEventStatus, AlertRule
from whatisup.models.incident import Incident, IncidentScope
from whatisup.models.monitor import Monitor
from whatisup.models.probe import Probe
from whatisup.models.result import CheckResult, CheckStatus
from whatisup.services.alert import dispatch_alert, maybe_digest_or_dispatch
from whatisup.services.maintenance import is_in_maintenance
from whatisup.services.stats import invalidate_uptime_cache, latest_results_subq

logger = structlog.get_logger(__name__)

# A monitor is considered "flapping" if it toggles state more than this many times
# within the flapping window
FLAP_THRESHOLD = 5
FLAP_WINDOW_MINUTES = 10


async def _is_flapping(db: AsyncSession, monitor_id: uuid.UUID) -> bool:
    """Detect rapid up/down oscillation within FLAP_WINDOW_MINUTES."""
    cutoff = datetime.now(UTC) - timedelta(minutes=FLAP_WINDOW_MINUTES)
    rows = (await db.execute(
        select(CheckResult.status, CheckResult.checked_at)
        .where(
            CheckResult.monitor_id == monitor_id,
            CheckResult.checked_at >= cutoff,
        )
        .order_by(CheckResult.checked_at.asc())
    )).all()

    if len(rows) < FLAP_THRESHOLD:
        return False

    transitions = sum(
        1 for i in range(1, len(rows))
        if (rows[i].status == CheckStatus.up) != (rows[i - 1].status == CheckStatus.up)
    )
    return transitions >= FLAP_THRESHOLD


async def _correlate_common_cause(
    db: AsyncSession,
    monitor_id: uuid.UUID,
    affected_probe_ids: list[str],
    publish_event,
) -> None:
    """
    If multiple monitors became down at the same time via the same probes,
    emit a correlation event for dashboard visibility.
    """
    if not affected_probe_ids:
        return

    window_start = datetime.now(UTC) - timedelta(seconds=90)

    # Find monitors that recently opened an incident with overlapping affected probes
    open_incidents = (await db.execute(
        select(Incident).where(
            Incident.resolved_at.is_(None),
            Incident.started_at >= window_start,
            Incident.monitor_id != monitor_id,
        )
    )).scalars().all()

    correlated = []
    for inc in open_incidents:
        overlap = set(inc.affected_probe_ids) & set(affected_probe_ids)
        if overlap:
            correlated.append(str(inc.monitor_id))

    if correlated:
        logger.info(
            "common_cause_detected",
            monitor_id=str(monitor_id),
            correlated_monitors=correlated,
            shared_probes=affected_probe_ids,
        )
        await publish_event({
            "type": "common_cause_detected",
            "monitor_id": str(monitor_id),
            "correlated_monitor_ids": correlated,
            "shared_probe_ids": affected_probe_ids,
        })


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

    rules = (await db.execute(
        select(AlertRule)
        .where(or_(*conditions))
        .options(selectinload(AlertRule.channels))
    )).scalars().all()

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
            probes = (await db.execute(
                select(Probe).where(Probe.id.in_(probe_uuids))
            )).scalars().all()
            probe_names = {str(p.id): p.name for p in probes}

    ctx = {
        "monitor_name": monitor.name,
        "check_type": monitor.check_type,
        "probe_names": probe_names,
    }

    now = datetime.now(UTC)

    for rule in rules:
        # H-10: min_duration_seconds — skip if incident too short for "opened" events
        if (event_type == "incident_opened"
                and rule.min_duration_seconds > 0
                and (now - incident.started_at).total_seconds() < rule.min_duration_seconds):
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
                last_event = (await db.execute(
                    select(AlertEvent)
                    .where(
                        AlertEvent.incident_id == incident.id,
                        AlertEvent.channel_id.in_(channel_ids),
                        AlertEvent.status == AlertEventStatus.sent,
                    )
                    .order_by(AlertEvent.sent_at.desc())
                    .limit(1)
                )).scalar_one_or_none()
                if last_event:
                    minutes_since = (now - last_event.sent_at).total_seconds() / 60
                    if minutes_since < rule.renotify_after_minutes:
                        continue
            # Dispatch renotify directly (digest ne s'applique pas au renotify)
            for channel in rule.channels:
                await dispatch_alert(db, incident, channel, "incident_opened", ctx=ctx)
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
            if not (result.ssl_valid is False or
                    (result.ssl_days_remaining is not None
                     and monitor.ssl_expiry_warn_days is not None
                     and result.ssl_days_remaining <= monitor.ssl_expiry_warn_days)):
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
    monitor = (await db.execute(
        select(Monitor).where(Monitor.id == monitor_id)
    )).scalar_one_or_none()
    group_id = monitor.group_id if monitor else None

    in_maintenance = await is_in_maintenance(db, monitor_id, group_id)
    if in_maintenance:
        logger.info("check_suppressed_maintenance", monitor_id=str(monitor_id))
        return

    # Invalidate uptime cache — a new result arrived, cached stats are stale
    await invalidate_uptime_cache(monitor_id)

    # Fetch all active probes
    active_probes = (await db.execute(
        select(Probe).where(Probe.is_active)
    )).scalars().all()

    if not active_probes:
        return

    active_probe_ids = {p.id for p in active_probes}

    # Batch query: latest result per probe for this monitor (replaces N individual queries)
    latest_subq = latest_results_subq(
        CheckResult.monitor_id == monitor_id,
        group_col=CheckResult.probe_id,
    )
    batch_results = (await db.execute(
        select(CheckResult)
        .join(
            latest_subq,
            (CheckResult.probe_id == latest_subq.c.probe_id)
            & (CheckResult.checked_at == latest_subq.c.max_at),
        )
        .where(CheckResult.monitor_id == monitor_id)
    )).scalars().all()

    latest_by_probe: dict[uuid.UUID, CheckResult] = {
        r.probe_id: r
        for r in batch_results
        if r.probe_id in active_probe_ids
    }

    if not latest_by_probe:
        return

    probes_total = len(latest_by_probe)
    probes_down = sum(
        1 for r in latest_by_probe.values()
        if r.status in (CheckStatus.down, CheckStatus.timeout, CheckStatus.error)
    )
    affected_probe_ids = [
        str(pid) for pid, r in latest_by_probe.items()
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
        flapping = await _is_flapping(db, monitor_id)
        if flapping:
            logger.info(
                "flapping_detected",
                monitor_id=str(monitor_id),
                probes_down=probes_down,
            )
            await publish_event({
                "type": "flapping_detected",
                "monitor_id": str(monitor_id),
                "probes_down": probes_down,
                "probes_total": probes_total,
            })
            return

    # Fetch open incident for this monitor
    open_incident = (await db.execute(
        select(Incident).where(
            Incident.monitor_id == monitor_id,
            Incident.resolved_at.is_(None),
        )
    )).scalar_one_or_none()

    now = datetime.now(UTC)

    if scope is not None and open_incident is None:
        # Open a new incident
        incident = Incident(
            monitor_id=monitor_id,
            started_at=now,
            scope=scope,
            affected_probe_ids=affected_probe_ids,
        )
        db.add(incident)
        await db.flush()

        logger.info(
            "incident_opened",
            monitor_id=str(monitor_id),
            scope=scope.value,
            probes_down=probes_down,
            probes_total=probes_total,
        )

        await publish_event({
            "type": "incident_opened",
            "monitor_id": str(monitor_id),
            "incident_id": str(incident.id),
            "scope": scope.value,
            "affected_probes": affected_probe_ids,
            "started_at": now.isoformat(),
        })

        # Fire alerts for incident open
        await _fire_alerts(db, incident, monitor, result, "incident_opened")

        # Detect common cause across monitors
        await _correlate_common_cause(db, monitor_id, affected_probe_ids, publish_event)

    elif scope is not None and open_incident is not None:
        # Update scope/affected probes if changed
        if (open_incident.scope != scope
                or set(open_incident.affected_probe_ids) != set(affected_probe_ids)):
            open_incident.scope = scope
            open_incident.affected_probe_ids = affected_probe_ids

        # H-11: fire renotify alerts — only load rules if any have renotify configured
        # to avoid a DB query on every check result when no rules use this feature
        renotify_conditions = [AlertRule.monitor_id == monitor.id]
        if monitor.group_id:
            renotify_conditions.append(AlertRule.group_id == monitor.group_id)
        has_renotify = (await db.execute(
            select(AlertRule.id).where(
                or_(*renotify_conditions),
                AlertRule.renotify_after_minutes.isnot(None),
            ).limit(1)
        )).scalar_one_or_none()
        if has_renotify:
            await _fire_alerts(db, open_incident, monitor, result, "incident_renotify")

    elif scope is None and open_incident is not None:
        # Resolve incident
        duration = int((now - open_incident.started_at).total_seconds())
        open_incident.resolved_at = now
        open_incident.duration_seconds = duration

        logger.info(
            "incident_resolved",
            monitor_id=str(monitor_id),
            incident_id=str(open_incident.id),
            duration_seconds=duration,
        )

        await publish_event({
            "type": "incident_resolved",
            "monitor_id": str(monitor_id),
            "incident_id": str(open_incident.id),
            "duration_seconds": duration,
            "resolved_at": now.isoformat(),
        })

        # Fire alerts for incident resolve
        await _fire_alerts(db, open_incident, monitor, result, "incident_resolved")
