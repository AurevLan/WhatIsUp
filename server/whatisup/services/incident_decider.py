"""Incident decision primitives — flapping & dependency suppression.

Pure-ish helpers extracted from ``services.incident`` so they can be unit-tested
in isolation. Each function takes an ``AsyncSession`` and reads from the DB but
does not mutate state, dispatch alerts, or publish events.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.models.incident import Incident
from whatisup.models.monitor import Monitor, MonitorDependency
from whatisup.models.result import CheckResult, CheckStatus

# Global defaults — overridden per-monitor by flap_threshold / flap_window_minutes
_DEFAULT_FLAP_THRESHOLD = 5
_DEFAULT_FLAP_WINDOW_MINUTES = 10

# Maximum hops walked when traversing the dependency chain. Keeps suppression
# bounded even on misconfigured graphs.
_DEPENDENCY_MAX_DEPTH = 5


async def is_flapping(db: AsyncSession, monitor: Monitor) -> bool:
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


async def has_ancestor_incident(
    db: AsyncSession,
    monitor_id: uuid.UUID,
    visited: set[uuid.UUID] | None = None,
    depth: int = 0,
) -> bool:
    """True if any ancestor in the dependency chain has an open incident.

    Follows the dependency graph recursively up to ``_DEPENDENCY_MAX_DEPTH``
    hops to handle transitive suppression (e.g. A -> B -> C: if A is down,
    both B and C are suppressed).
    """
    if depth > _DEPENDENCY_MAX_DEPTH:
        return False
    if visited is None:
        visited = set()
    if monitor_id in visited:
        return False
    visited.add(monitor_id)

    parents = (
        (
            await db.execute(
                select(MonitorDependency).where(
                    MonitorDependency.child_id == monitor_id,
                    MonitorDependency.suppress_on_parent_down.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )

    if not parents:
        return False

    for dep in parents:
        has_incident = (
            await db.execute(
                select(Incident.id)
                .where(
                    Incident.monitor_id == dep.parent_id,
                    Incident.resolved_at.is_(None),
                )
                .limit(1)
            )
        ).scalar_one_or_none()

        if has_incident:
            return True

        if await has_ancestor_incident(db, dep.parent_id, visited, depth + 1):
            return True

    return False


async def is_suppressed_by_dependency(db: AsyncSession, monitor_id: uuid.UUID) -> bool:
    """Return True if any ancestor monitor in the dependency chain has an open incident."""
    return await has_ancestor_incident(db, monitor_id)
