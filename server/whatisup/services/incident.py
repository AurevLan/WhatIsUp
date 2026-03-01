"""Incident detection — multi-probe correlation logic."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.models.incident import Incident, IncidentScope
from whatisup.models.probe import Probe
from whatisup.models.result import CheckResult, CheckStatus

logger = structlog.get_logger(__name__)


async def process_check_result(
    db: AsyncSession,
    result: CheckResult,
    publish_event,  # callable(event_dict) for WebSocket broadcast
) -> None:
    """
    Called after a new CheckResult is stored.
    Performs multi-probe correlation and manages incident lifecycle.
    """
    monitor_id = result.monitor_id

    # Fetch all active probes
    active_probes = (await db.execute(
        select(Probe).where(Probe.is_active is True)
    )).scalars().all()

    if not active_probes:
        return

    [p.id for p in active_probes]

    # Get the most recent result per active probe for this monitor
    latest_by_probe: dict[uuid.UUID, CheckResult] = {}
    for probe in active_probes:
        latest = (await db.execute(
            select(CheckResult)
            .where(
                CheckResult.monitor_id == monitor_id,
                CheckResult.probe_id == probe.id,
            )
            .order_by(CheckResult.checked_at.desc())
            .limit(1)
        )).scalar_one_or_none()
        if latest is not None:
            latest_by_probe[probe.id] = latest

    if not latest_by_probe:
        return

    probes_total = len(latest_by_probe)
    probes_down = sum(
        1 for r in latest_by_probe.values()
        if r.status in (CheckStatus.down, CheckStatus.timeout, CheckStatus.error)
    )
    probes_total - probes_down
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

    elif scope is not None and open_incident is not None:
        # Update scope/affected probes if changed
        if (open_incident.scope != scope
                or set(open_incident.affected_probe_ids) != set(affected_probe_ids)):
            open_incident.scope = scope
            open_incident.affected_probe_ids = affected_probe_ids

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
