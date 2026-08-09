"""Incident lifecycle orchestrator.

Thin coordinator over the extracted services:
- ``incident_decider``: flapping detection + dependency suppression checks.
- ``incident_correlation``: probe / group / dependency grouping strategies.
- ``incident_alerts``: alert rule evaluation and channel dispatch.
- ``incident_slo``: V2 Health Engine SLO-driven open / resolve.

This module owns the legacy per-probe open/update/resolve lifecycle and
post-decider side effects (composite cascade, schema drift, anomaly detection,
auto-pause). SLO bridge functions are re-exported below so existing imports
``from whatisup.services.incident import open_incident_from_health`` keep
working.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import structlog
from redis.exceptions import RedisError
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.core.config import get_settings
from whatisup.models.alert import AlertCondition, AlertRule
from whatisup.models.incident import (
    IS_AVAILABILITY_INCIDENT,
    Incident,
    IncidentGroup,
    IncidentScope,
)
from whatisup.models.monitor import Monitor
from whatisup.models.probe import Probe
from whatisup.models.result import CheckResult, CheckStatus
from whatisup.services.anomaly import compute_zscore
from whatisup.services.correlation import update_patterns_for_group
from whatisup.services.incident_alerts import fire_alerts
from whatisup.services.incident_correlation import (
    correlate_by_dependency,
    correlate_by_group,
    correlate_common_cause,
)
from whatisup.services.incident_decider import (
    has_ancestor_incident,
    is_flapping,
    is_suppressed_by_dependency,
)
from whatisup.services.incident_slo import open_incident_from_health, resolve_incident_for_slo
from whatisup.services.maintenance import is_group_maintenance_suppressed, is_in_maintenance
from whatisup.services.stats import invalidate_uptime_cache, latest_results_subq

logger = structlog.get_logger(__name__)

# Backwards-compatible private aliases — external callers (heartbeat, renotify)
# and tests still import these names from ``services.incident``.
_is_flapping = is_flapping
_has_ancestor_incident = has_ancestor_incident
_is_suppressed_by_dependency = is_suppressed_by_dependency
_correlate_common_cause = correlate_common_cause
_correlate_by_group = correlate_by_group
_correlate_by_dependency = correlate_by_dependency
_fire_alerts = fire_alerts

# SLO bridge — re-exported so ``services.health`` and tests can keep importing
# ``open_incident_from_health`` / ``resolve_incident_for_slo`` from here.
__all__ = [
    "open_incident_from_health",
    "process_check_result",
    "resolve_incident_for_slo",
]


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
                IS_AVAILABILITY_INCIDENT,
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


async def _maybe_promote_suppressed_incident(
    db: AsyncSession,
    incident: Incident,
    monitor: Monitor,
    result: CheckResult,
    publish_event,
) -> bool:
    """Promote a still-open incident that never fired its opening alert.

    BUG-P0: an incident created while suppressed — inside a maintenance window,
    or behind a parent that has since recovered — keeps ``resolved_at IS NULL``.
    When the outage outlives the suppression, the next check finds it as the
    "already open" incident and only ever sends renotify, so the *opening*
    alert is never delivered and the real outage stays silent.

    The caller guarantees we are no longer in a maintenance window. If no
    parent dependency suppresses the monitor anymore, flip the flag, run
    correlation and fire the opening alert. Returns True when promoted.
    """
    if not incident.dependency_suppressed:
        return False
    if await _is_suppressed_by_dependency(db, monitor.id):
        return False  # still legitimately suppressed by a down parent

    incident.dependency_suppressed = False
    await db.flush()
    logger.info(
        "incident_promoted_from_suppressed",
        monitor_id=str(monitor.id),
        incident_id=str(incident.id),
    )
    await publish_event(
        {
            "type": "incident_opened",
            "monitor_id": str(monitor.id),
            "incident_id": str(incident.id),
            "scope": incident.scope.value,
            "affected_probes": incident.affected_probe_ids,
            "started_at": incident.started_at.isoformat(),
            "dependency_suppressed": False,
        }
    )

    await _correlate_common_cause(db, incident, incident.affected_probe_ids, publish_event)
    if incident.group_id is None:
        await _correlate_by_group(db, incident, monitor, publish_event)
    if incident.group_id is None:
        await _correlate_by_dependency(db, incident, monitor.id, publish_event)

    extra_ctx = (
        {"correlated_group_id": str(incident.group_id)} if incident.group_id is not None else None
    )
    await _fire_alerts(db, incident, monitor, result, "incident_opened", extra_ctx=extra_ctx)
    return True


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
                        IS_AVAILABILITY_INCIDENT,
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
                (
                    await db.execute(
                        select(_Monitor.id).where(
                            _Monitor.group_id == group_id,
                            _Monitor.enabled.is_(True),
                        )
                    )
                )
                .scalars()
                .all()
            )
            if all_in_group:
                open_incidents_count = (
                    await db.execute(
                        select(func.count(_Incident.id)).where(
                            _Incident.monitor_id.in_(all_in_group),
                            _Incident.resolved_at.is_(None),
                            _Incident.alert_rule_id.is_(None),
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

    # V2 Global Health Engine opt-in: skip the per-probe decider — SLO
    # evaluation in services/health.evaluate_slos() drives incidents instead.
    # Post-decider side effects (composite cascade, schema drift, anomaly,
    # auto-pause) still run below. Bypassed entirely when LEGACY_INCIDENT_ENGINE
    # is set (M5 emergency rollback — no code change, no migration).
    settings = get_settings()
    if monitor and monitor.health_engine_enabled and not settings.legacy_incident_engine:
        await _post_decider_side_effects(db, result, monitor, publish_event)
        return

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
                IS_AVAILABILITY_INCIDENT,
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

        # V2-01-01 — fire the diagnostic collection request to every probe
        # currently reporting the monitor as down. Best-effort: errors are
        # swallowed inside the helper, this must not break the incident path.
        try:
            from whatisup.services.diagnostics import enqueue_diagnostic_requests

            await enqueue_diagnostic_requests(
                incident_id=incident.id,
                monitor_id=monitor_id,
                target=monitor.url,
                check_type=monitor.check_type,
                affected_probe_ids=affected_probe_ids,
            )
        except (ImportError, RedisError, OSError) as exc:
            logger.warning(
                "diagnostic_enqueue_in_pipeline_failed",
                incident_id=str(incident.id),
                error_type=type(exc).__name__,
                error=str(exc),
            )

        # V2-02-02 — classify network verdict using the latest_by_probe map we
        # already loaded. Best-effort: any failure leaves verdict null and is
        # logged. The background task will retry every 5 min while open.
        try:
            from whatisup.services.network_verdict import classify_network_verdict

            await classify_network_verdict(
                db, incident, latest_by_probe=latest_by_probe, persist=True
            )
        except (ImportError, SQLAlchemyError, OSError) as exc:
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

        # BUG-P0: a suppressed incident (maintenance over, or parent recovered)
        # whose outage is still ongoing must finally fire its opening alert
        # instead of silently flowing into the renotify path.
        if await _maybe_promote_suppressed_incident(
            db, open_incident, monitor, result, publish_event
        ):
            await _post_decider_side_effects(db, result, monitor, publish_event)
            return

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
                        select(Incident)
                        .where(
                            Incident.group_id == group.id,
                            Incident.resolved_at.is_(None),
                        )
                        .limit(1)
                    )
                ).scalar_one_or_none()
                if siblings is None:
                    # All incidents in group are resolved
                    group.status = "resolved"
                    group.resolved_at = now
                    logger.info("incident_group_resolved", group_id=str(group.id))

    await _post_decider_side_effects(db, result, monitor, publish_event)


async def _post_decider_side_effects(
    db: AsyncSession,
    result: CheckResult,
    monitor: Monitor | None,
    publish_event,
) -> None:
    """Side effects that fire on every CheckResult regardless of decider path.

    Shared between the legacy per-probe pipeline and the V2 Global Health
    Engine: composite cascade, schema drift, anomaly detection, auto-pause.
    """
    if monitor is None:
        return

    monitor_id = monitor.id

    # Propagate state change to any composite monitors that include this monitor
    # (skip if this monitor itself is composite to avoid infinite recursion)
    if monitor.check_type != "composite":
        from whatisup.services.composite import evaluate_composite_parents

        await evaluate_composite_parents(db, monitor_id, publish_event)

    # Schema drift detection — update baseline on first result, fire alerts on change
    if (
        monitor.schema_drift_enabled
        and result.schema_fingerprint
        and result.status == CheckStatus.up
    ):
        if not monitor.schema_baseline:
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
    if result.status == CheckStatus.up and result.response_time_ms is not None:
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
    if monitor.auto_pause_after and monitor.enabled:
        last_n = (
            (
                await db.execute(
                    select(CheckResult.status)
                    .where(CheckResult.monitor_id == monitor.id)
                    .order_by(CheckResult.checked_at.desc())
                    .limit(monitor.auto_pause_after)
                )
            )
            .scalars()
            .all()
        )
        if len(last_n) >= monitor.auto_pause_after and all(s != CheckStatus.up for s in last_n):
            monitor.enabled = False
            logger.warning(
                "auto_pause_triggered",
                monitor_id=str(monitor.id),
                consecutive_failures=len(last_n),
            )
