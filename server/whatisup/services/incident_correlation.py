"""Incident correlation strategies — probe / group / dependency.

Each strategy may attach the incident to an ``IncidentGroup`` and emit a
``common_cause_detected`` event. They are called sequentially: the first one
that groups the incident short-circuits the rest (callers check
``incident.group_id is None`` between calls).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
import structlog
from sqlalchemy import cast, select
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.core.database import dialect_name
from whatisup.models.incident import Incident, IncidentGroup
from whatisup.models.monitor import Monitor, MonitorDependency

logger = structlog.get_logger(__name__)


async def correlate_common_cause(
    db: AsyncSession,
    incident: Incident,
    affected_probe_ids: list[str],
    publish_event,
) -> None:
    """Group incidents that share affected probe IDs within a 90-second window."""
    if not affected_probe_ids:
        return

    monitor_id = incident.monitor_id
    window_start = datetime.now(UTC) - timedelta(seconds=90)

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
        open_incidents = (await db.execute(base_query)).scalars().all()
        probe_set = set(affected_probe_ids)
        correlated_incidents = [
            inc for inc in open_incidents if set(inc.affected_probe_ids) & probe_set
        ]

    if not correlated_incidents:
        return

    existing_group_id: uuid.UUID | None = next(
        (inc.group_id for inc in correlated_incidents if inc.group_id is not None),
        None,
    )

    now = datetime.now(UTC)

    group: IncidentGroup | None = None
    if existing_group_id:
        group = await db.get(IncidentGroup, existing_group_id)
        if group:
            merged = list(set(group.cause_probe_ids) | set(affected_probe_ids))
            group.cause_probe_ids = merged

    if group is None:
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
        await db.flush()
        for inc in correlated_incidents:
            if inc.group_id is None:
                inc.group_id = group.id

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


async def correlate_by_group(
    db: AsyncSession,
    incident: Incident,
    monitor: Monitor,
    publish_event,
) -> None:
    """Group siblings of the same MonitorGroup when ≥50% are down within 2 min.

    Detects shared infrastructure failures invisible to probe-level correlation.
    """
    if not monitor.group_id or incident.group_id is not None:
        return

    window_start = datetime.now(UTC) - timedelta(minutes=2)

    group_monitors = (
        (
            await db.execute(
                select(Monitor.id).where(
                    Monitor.group_id == monitor.group_id,
                    Monitor.enabled.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )

    if len(group_monitors) < 2:
        return

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

    down_count = len(sibling_incidents) + 1  # +1 for current incident
    threshold = len(group_monitors) / 2
    if down_count < threshold:
        return

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


async def correlate_by_dependency(
    db: AsyncSession,
    incident: Incident,
    monitor_id: uuid.UUID,
    publish_event,
) -> None:
    """Cascade correlation across MonitorDependency edges within a 5-minute window."""
    if incident.group_id is not None:
        return

    window_start = datetime.now(UTC) - timedelta(minutes=5)
    now = datetime.now(UTC)

    parent_deps = (
        (
            await db.execute(
                select(MonitorDependency.parent_id).where(MonitorDependency.child_id == monitor_id)
            )
        )
        .scalars()
        .all()
    )

    child_deps = (
        (
            await db.execute(
                select(MonitorDependency.child_id).where(MonitorDependency.parent_id == monitor_id)
            )
        )
        .scalars()
        .all()
    )

    related_ids = list(set(parent_deps) | set(child_deps))
    if not related_ids:
        return

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
