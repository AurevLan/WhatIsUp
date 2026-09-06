"""Tests for incident_decider — dependency suppression.

Flapping detection (``is_flapping``) was removed in plan Cap v2 4b along with
the legacy per-probe decider that was its only caller — see
``services/incident_decider.py`` module docstring.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.models.incident import Incident, IncidentScope
from whatisup.models.monitor import Monitor, MonitorDependency
from whatisup.models.user import User
from whatisup.services.incident_decider import has_ancestor_incident, is_suppressed_by_dependency


async def _new_monitor(db: AsyncSession, owner: User, name: str = "mon") -> Monitor:
    m = Monitor(name=name, url=f"http://{name}.example.com", owner_id=owner.id)
    db.add(m)
    await db.flush()
    return m


# ── has_ancestor_incident ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_has_ancestor_incident_no_parents(
    service_db: AsyncSession, test_monitor: Monitor
) -> None:
    """Monitor with no dependencies → no ancestor incident."""
    assert await has_ancestor_incident(service_db, test_monitor.id) is False


@pytest.mark.asyncio
async def test_has_ancestor_incident_finds_direct_parent(
    service_db: AsyncSession, test_user: User
) -> None:
    """Direct parent with an open incident → True."""
    parent = await _new_monitor(service_db, test_user, "parent")
    child = await _new_monitor(service_db, test_user, "child")
    service_db.add(MonitorDependency(parent_id=parent.id, child_id=child.id))
    service_db.add(
        Incident(
            monitor_id=parent.id,
            started_at=datetime.now(UTC),
            scope=IncidentScope.global_,
            affected_probe_ids=[],
        )
    )
    await service_db.flush()

    assert await has_ancestor_incident(service_db, child.id) is True
    assert await is_suppressed_by_dependency(service_db, child.id) is True


@pytest.mark.asyncio
async def test_has_ancestor_incident_recurses_through_chain(
    service_db: AsyncSession, test_user: User
) -> None:
    """A → B → C: if A is down, C is suppressed via B."""
    a = await _new_monitor(service_db, test_user, "a")
    b = await _new_monitor(service_db, test_user, "b")
    c = await _new_monitor(service_db, test_user, "c")
    service_db.add(MonitorDependency(parent_id=a.id, child_id=b.id))
    service_db.add(MonitorDependency(parent_id=b.id, child_id=c.id))
    service_db.add(
        Incident(
            monitor_id=a.id,
            started_at=datetime.now(UTC),
            scope=IncidentScope.global_,
            affected_probe_ids=[],
        )
    )
    await service_db.flush()

    assert await has_ancestor_incident(service_db, c.id) is True


@pytest.mark.asyncio
async def test_has_ancestor_incident_ignores_disabled_suppression(
    service_db: AsyncSession, test_user: User
) -> None:
    """suppress_on_parent_down=False → dependency is skipped during traversal."""
    parent = await _new_monitor(service_db, test_user, "parent2")
    child = await _new_monitor(service_db, test_user, "child2")
    service_db.add(
        MonitorDependency(parent_id=parent.id, child_id=child.id, suppress_on_parent_down=False)
    )
    service_db.add(
        Incident(
            monitor_id=parent.id,
            started_at=datetime.now(UTC),
            scope=IncidentScope.global_,
            affected_probe_ids=[],
        )
    )
    await service_db.flush()

    assert await has_ancestor_incident(service_db, child.id) is False


@pytest.mark.asyncio
async def test_has_ancestor_incident_skips_resolved_parent_incidents(
    service_db: AsyncSession, test_user: User
) -> None:
    """A resolved parent incident does not suppress a child."""
    parent = await _new_monitor(service_db, test_user, "parent3")
    child = await _new_monitor(service_db, test_user, "child3")
    service_db.add(MonitorDependency(parent_id=parent.id, child_id=child.id))
    now = datetime.now(UTC)
    service_db.add(
        Incident(
            monitor_id=parent.id,
            started_at=now - timedelta(hours=1),
            resolved_at=now,
            duration_seconds=3600,
            scope=IncidentScope.global_,
            affected_probe_ids=[],
        )
    )
    await service_db.flush()

    assert await has_ancestor_incident(service_db, child.id) is False


@pytest.mark.asyncio
async def test_has_ancestor_incident_breaks_cycle(
    service_db: AsyncSession, test_user: User
) -> None:
    """A misconfigured cycle A→B→A must terminate without infinite recursion."""
    a = await _new_monitor(service_db, test_user, "cyc-a")
    b = await _new_monitor(service_db, test_user, "cyc-b")
    service_db.add(MonitorDependency(parent_id=a.id, child_id=b.id))
    service_db.add(MonitorDependency(parent_id=b.id, child_id=a.id))
    await service_db.flush()
    # No open incident anywhere — should still terminate and return False
    assert await has_ancestor_incident(service_db, a.id) is False
