"""Incident lifecycle orchestrator.

Thin coordinator over the extracted services:
- ``incident_decider``: dependency suppression checks.
- ``incident_correlation``: probe / group / dependency grouping strategies.
- ``incident_alerts``: alert rule evaluation and channel dispatch.
- ``incident_slo``: V2 Health Engine SLO-driven open / resolve — the only
  detection engine left since plan Cap v2 4b retired the legacy per-probe
  decider (``incident_decider.is_flapping`` went with it).

``process_check_result`` no longer opens or resolves availability incidents
itself — that's ``services.health.evaluate_slos`` / ``incident_slo`` now, on
every monitor. This module keeps: composite monitor lifecycle (no per-probe
consensus to speak of), maintenance suppression bookkeeping, and the
post-decider side effects shared by both callers of ``process_check_result``
and ``open_incident_from_health`` (composite cascade, schema drift, anomaly
detection, auto-pause). SLO bridge functions are re-exported below so
existing imports ``from whatisup.services.incident import
open_incident_from_health`` keep working.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.models.alert import AlertCondition, AlertRule
from whatisup.models.incident import (
    IS_AVAILABILITY_INCIDENT,
    Incident,
    IncidentScope,
)
from whatisup.models.monitor import Monitor
from whatisup.models.result import CheckResult, CheckStatus
from whatisup.services.anomaly import compute_zscore
from whatisup.services.incident_alerts import fire_alerts
from whatisup.services.incident_correlation import (
    correlate_by_dependency,
    correlate_by_group,
    correlate_common_cause,
)
from whatisup.services.incident_decider import has_ancestor_incident, is_suppressed_by_dependency
from whatisup.services.incident_slo import open_incident_from_health, resolve_incident_for_slo
from whatisup.services.maintenance import is_group_maintenance_suppressed, is_in_maintenance
from whatisup.services.stats import invalidate_uptime_cache

logger = structlog.get_logger(__name__)

# Backwards-compatible private aliases — external callers (heartbeat, renotify)
# and tests still import these names from ``services.incident``.
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


async def process_check_result(
    db: AsyncSession,
    result: CheckResult,
    publish_event,
) -> None:
    """Called after a new CheckResult is stored.

    Handles maintenance suppression bookkeeping, the composite-monitor
    lifecycle, and post-decider side effects. Availability incidents
    themselves are opened/resolved by ``services.health.evaluate_slos`` on
    every monitor (plan Cap v2 4b) — not here.
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

    # V2 Global Health Engine (plan Cap v2 4b): the only detection engine left.
    # SLO evaluation in services/health.evaluate_slos() drives availability
    # incidents instead — see incident_slo.open_incident_from_health /
    # resolve_incident_for_slo, called from health.ingest() on every
    # CheckResult (api/v1/probes.py), not from here. Post-decider side effects
    # (composite cascade, schema drift, anomaly, auto-pause) still run below
    # regardless of monitor.health_engine_enabled.
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
