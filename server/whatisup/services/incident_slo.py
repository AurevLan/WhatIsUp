"""V2 Global Health Engine bridge — SLO-driven incident lifecycle.

``services.health`` calls into these two functions when an SLO rule's verdict
changes. The legacy per-probe pipeline in ``services.incident.process_check_result``
still owns composite, schema drift, anomaly detection and auto-pause; we only
mint/resolve incidents here.

Diagnostic enqueue + correlation + alert dispatch are reused from the legacy
path so health-engine incidents are observability-equivalent.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.models.incident import Incident, IncidentGroup, IncidentScope
from whatisup.models.monitor import Monitor
from whatisup.services.incident_alerts import fire_alerts
from whatisup.services.incident_correlation import (
    correlate_by_dependency,
    correlate_by_group,
    correlate_common_cause,
)
from whatisup.services.incident_decider import is_suppressed_by_dependency
from whatisup.services.maintenance import is_in_maintenance
from whatisup.services.stats import invalidate_uptime_cache

logger = structlog.get_logger(__name__)


async def open_incident_from_health(
    db: AsyncSession,
    monitor: Monitor,
    slo_rule_id: uuid.UUID,
    trigger_kind: str,
    scope: IncidentScope,
    affected_probe_ids: list[str],
    reason: str,
    publish_event,
) -> Incident | None:
    """Open (or no-op if already open) an incident tied to an SLO rule.

    Idempotent on (monitor_id, slo_rule_id, resolved_at IS NULL): a second call
    while the incident is still live returns the existing row without firing
    duplicate alerts.
    """
    monitor_id = monitor.id

    if await is_in_maintenance(db, monitor_id, monitor.group_id):
        logger.info(
            "slo_incident_suppressed_maintenance",
            monitor_id=str(monitor_id),
            slo_rule_id=str(slo_rule_id),
        )
        return None

    existing = (
        await db.execute(
            select(Incident).where(
                Incident.monitor_id == monitor_id,
                Incident.slo_rule_id == slo_rule_id,
                Incident.resolved_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        # Refresh scope/probes if quorum membership shifted
        if existing.scope != scope or set(existing.affected_probe_ids) != set(affected_probe_ids):
            existing.scope = scope
            existing.affected_probe_ids = affected_probe_ids
            await db.flush()
        return existing

    now = datetime.now(UTC)
    suppressed = await is_suppressed_by_dependency(db, monitor_id)
    incident = Incident(
        monitor_id=monitor_id,
        started_at=now,
        scope=scope,
        affected_probe_ids=affected_probe_ids,
        dependency_suppressed=suppressed,
        first_failure_at=now,
        slo_rule_id=slo_rule_id,
        trigger_kind=trigger_kind,
    )
    db.add(incident)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        logger.info(
            "slo_incident_creation_deduplicated",
            monitor_id=str(monitor_id),
            slo_rule_id=str(slo_rule_id),
        )
        return None

    # Reuse the diagnostic + verdict pipeline so health-engine incidents are
    # observability-equivalent to legacy ones.
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
            "slo_diagnostic_enqueue_failed",
            incident_id=str(incident.id),
            error=str(exc),
        )

    logger.info(
        "slo_incident_opened",
        monitor_id=str(monitor_id),
        incident_id=str(incident.id),
        slo_rule_id=str(slo_rule_id),
        trigger_kind=trigger_kind,
        scope=scope.value,
        reason=reason,
        probes=len(affected_probe_ids),
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
            "trigger_kind": trigger_kind,
        }
    )

    if not suppressed:
        await correlate_common_cause(db, incident, affected_probe_ids, publish_event)
        if incident.group_id is None:
            await correlate_by_group(db, incident, monitor, publish_event)
        if incident.group_id is None:
            await correlate_by_dependency(db, incident, monitor_id, publish_event)
        extra_ctx = (
            {"correlated_group_id": str(incident.group_id)}
            if incident.group_id is not None
            else None
        )
        await fire_alerts(db, incident, monitor, None, "incident_opened", extra_ctx=extra_ctx)

    await invalidate_uptime_cache(monitor_id)
    return incident


async def resolve_incident_for_slo(
    db: AsyncSession,
    monitor: Monitor,
    slo_rule_id: uuid.UUID,
    publish_event,
    reason: str = "slo_recovered",
) -> Incident | None:
    """Resolve the open incident for an SLO rule, if any. No-op otherwise."""
    monitor_id = monitor.id
    incident = (
        await db.execute(
            select(Incident).where(
                Incident.monitor_id == monitor_id,
                Incident.slo_rule_id == slo_rule_id,
                Incident.resolved_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if incident is None:
        return None

    now = datetime.now(UTC)
    started = incident.started_at
    if started.tzinfo is None:
        started = started.replace(tzinfo=UTC)
    duration = int((now - started).total_seconds())
    incident.resolved_at = now
    incident.duration_seconds = duration
    incident.acked_at = None
    incident.acked_by_id = None
    incident.snooze_until = None
    await db.flush()

    logger.info(
        "slo_incident_resolved",
        monitor_id=str(monitor_id),
        incident_id=str(incident.id),
        slo_rule_id=str(slo_rule_id),
        duration_seconds=duration,
        reason=reason,
    )
    await publish_event(
        {
            "type": "incident_resolved",
            "monitor_id": str(monitor_id),
            "incident_id": str(incident.id),
            "duration_seconds": duration,
            "resolved_at": now.isoformat(),
        }
    )
    if not incident.dependency_suppressed:
        await fire_alerts(db, incident, monitor, None, "incident_resolved")

    if incident.group_id is not None:
        group = await db.get(IncidentGroup, incident.group_id)
        if group and group.status == "open":
            sibling = (
                await db.execute(
                    select(Incident)
                    .where(
                        Incident.group_id == group.id,
                        Incident.resolved_at.is_(None),
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()
            if sibling is None:
                group.status = "resolved"
                group.resolved_at = now

    await invalidate_uptime_cache(monitor_id)
    return incident
