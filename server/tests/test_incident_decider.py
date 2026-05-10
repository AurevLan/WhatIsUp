"""Tests for incident_decider — flapping detection + dependency suppression."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.models.incident import Incident, IncidentScope
from whatisup.models.monitor import Monitor, MonitorDependency
from whatisup.models.probe import Probe
from whatisup.models.result import CheckResult, CheckStatus
from whatisup.models.user import User
from whatisup.services.incident_decider import (
    has_ancestor_incident,
    is_flapping,
    is_suppressed_by_dependency,
)


async def _add_result(
    db: AsyncSession,
    monitor: Monitor,
    probe: Probe,
    status: CheckStatus,
    dt: datetime,
) -> CheckResult:
    r = CheckResult(
        monitor_id=monitor.id,
        probe_id=probe.id,
        checked_at=dt,
        status=status,
    )
    db.add(r)
    await db.flush()
    return r


async def _new_monitor(db: AsyncSession, owner: User, name: str = "mon") -> Monitor:
    m = Monitor(name=name, url=f"http://{name}.example.com", owner_id=owner.id)
    db.add(m)
    await db.flush()
    return m


# ── is_flapping ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_is_flapping_returns_false_when_too_few_results(
    service_db: AsyncSession, test_monitor: Monitor, test_probe: Probe
) -> None:
    """Below the threshold count: no flapping verdict."""
    now = datetime.now(UTC)
    # Default threshold = 5 — only 3 results
    for i in range(3):
        await _add_result(
            service_db, test_monitor, test_probe, CheckStatus.up, now - timedelta(minutes=i)
        )
    assert await is_flapping(service_db, test_monitor) is False


@pytest.mark.asyncio
async def test_is_flapping_returns_true_when_oscillation_exceeds_threshold(
    service_db: AsyncSession, test_monitor: Monitor, test_probe: Probe
) -> None:
    """Alternating up/down >= flap_threshold within window triggers flapping."""
    now = datetime.now(UTC)
    # 6 alternating results → 5 transitions → meets default threshold of 5
    statuses = [
        CheckStatus.up,
        CheckStatus.down,
        CheckStatus.up,
        CheckStatus.down,
        CheckStatus.up,
        CheckStatus.down,
    ]
    for i, status in enumerate(statuses):
        await _add_result(
            service_db, test_monitor, test_probe, status, now - timedelta(seconds=60 - i * 10)
        )
    assert await is_flapping(service_db, test_monitor) is True


@pytest.mark.asyncio
async def test_is_flapping_ignores_results_outside_window(
    service_db: AsyncSession, test_monitor: Monitor, test_probe: Probe
) -> None:
    """Old results outside flap_window_minutes are excluded."""
    now = datetime.now(UTC)
    # 6 alternating but 30 min in the past — outside the default 10-min window
    statuses = [CheckStatus.up, CheckStatus.down] * 3
    for i, status in enumerate(statuses):
        await _add_result(
            service_db, test_monitor, test_probe, status, now - timedelta(minutes=30 + i)
        )
    assert await is_flapping(service_db, test_monitor) is False


@pytest.mark.asyncio
async def test_is_flapping_respects_per_monitor_threshold(
    service_db: AsyncSession, test_user: User, test_probe: Probe
) -> None:
    """Per-monitor flap_threshold overrides the global default."""
    now = datetime.now(UTC)
    monitor = await _new_monitor(service_db, test_user, "low-threshold")
    monitor.flap_threshold = 2
    monitor.flap_window_minutes = 10
    await service_db.flush()

    # 3 alternating results → 2 transitions → meets threshold=2
    statuses = [CheckStatus.up, CheckStatus.down, CheckStatus.up]
    for i, status in enumerate(statuses):
        await _add_result(
            service_db, monitor, test_probe, status, now - timedelta(seconds=60 - i * 10)
        )
    assert await is_flapping(service_db, monitor) is True


@pytest.mark.asyncio
async def test_is_flapping_returns_false_when_all_same_status(
    service_db: AsyncSession, test_monitor: Monitor, test_probe: Probe
) -> None:
    """No transitions = not flapping, even with many results."""
    now = datetime.now(UTC)
    for i in range(10):
        await _add_result(
            service_db, test_monitor, test_probe, CheckStatus.up, now - timedelta(seconds=i * 10)
        )
    assert await is_flapping(service_db, test_monitor) is False


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
