"""Incident decision primitives — dependency suppression.

Pure-ish helpers extracted from ``services.incident`` so they can be unit-tested
in isolation. Each function takes an ``AsyncSession`` and reads from the DB but
does not mutate state, dispatch alerts, or publish events.

Flapping detection (``is_flapping``) lived here until plan Cap v2 4b: it was
only ever consulted by the legacy per-probe decider, which retired along with
it. The Global Health Engine's quorum window + ``cooldown_seconds`` play the
equivalent damping role for the surviving detection path — see CLAUDE.md
"Health Engine V2 — ops prod".
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.models.incident import IS_AVAILABILITY_INCIDENT, Incident
from whatisup.models.monitor import MonitorDependency

# Maximum hops walked when traversing the dependency chain. Keeps suppression
# bounded even on misconfigured graphs.
_DEPENDENCY_MAX_DEPTH = 5


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
                    IS_AVAILABILITY_INCIDENT,
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
