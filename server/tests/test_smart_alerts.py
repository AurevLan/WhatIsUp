"""Tests for smart alert presets, auto-rules, threshold suggestions, and correlations."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.models.alert import AlertCondition
from whatisup.models.correlation_pattern import CorrelationPattern
from whatisup.models.incident import Incident, IncidentGroup, IncidentScope
from whatisup.models.monitor import Monitor, MonitorDependency, MonitorGroup
from whatisup.models.probe import Probe
from whatisup.models.result import CheckResult, CheckStatus
from whatisup.models.user import User
from whatisup.services.alert_presets import get_presets
from whatisup.services.correlation import get_correlated_monitors, update_patterns_for_group
from whatisup.services.incident import (
    _correlate_by_dependency,
    _correlate_by_group,
    _correlate_common_cause,
)

# ── Helpers ──────────────────────────────────────────────────────────────────


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


class _EventCollector:
    def __init__(self) -> None:
        self.events: list[dict] = []

    async def __call__(self, event: dict) -> None:
        self.events.append(event)


async def _add_result(
    db: AsyncSession,
    monitor: Monitor,
    probe: Probe,
    status: CheckStatus,
    dt: datetime | None = None,
    response_time_ms: int | None = None,
) -> CheckResult:
    r = CheckResult(
        monitor_id=monitor.id,
        probe_id=probe.id,
        checked_at=dt or datetime.now(UTC),
        status=status,
        response_time_ms=response_time_ms,
    )
    db.add(r)
    await db.flush()
    return r


# ══════════════════════════════════════════════════════════════════════════════
# Alert Presets
# ══════════════════════════════════════════════════════════════════════════════


def test_presets_http_has_any_down() -> None:
    presets = get_presets("http")
    conditions = [p["condition"] for p in presets]
    assert AlertCondition.any_down in conditions
    assert AlertCondition.ssl_expiry in conditions


def test_presets_heartbeat_has_any_down() -> None:
    presets = get_presets("heartbeat")
    assert len(presets) == 1
    assert presets[0]["condition"] == AlertCondition.any_down
    assert presets[0]["default"] is True


def test_presets_unknown_type_falls_back_to_http() -> None:
    presets = get_presets("nonexistent")
    assert presets == get_presets("http")


def test_presets_scenario_has_response_time() -> None:
    presets = get_presets("scenario")
    conditions = [p["condition"] for p in presets]
    assert AlertCondition.response_time_above in conditions


# ══════════════════════════════════════════════════════════════════════════════
# Auto-rules via HTTP endpoints
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_presets_endpoint(client: AsyncClient, user_token: str) -> None:
    resp = await client.get("/api/v1/alerts/presets/http", headers=_auth(user_token))
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 2


@pytest.mark.asyncio
async def test_auto_rules_creates_defaults(client: AsyncClient, user_token: str) -> None:
    # Create monitor + channel
    mon = await client.post(
        "/api/v1/monitors/",
        json={"name": "Auto Mon", "url": "https://example.com"},
        headers=_auth(user_token),
    )
    assert mon.status_code == 201
    monitor_id = mon.json()["id"]

    ch = await client.post(
        "/api/v1/alerts/channels",
        json={
            "name": "AutoCh",
            "type": "webhook",
            "config": {"url": "https://hooks.example.com/a"},
        },
        headers=_auth(user_token),
    )
    assert ch.status_code == 201
    channel_id = ch.json()["id"]

    # Create auto-rules
    resp = await client.post(
        f"/api/v1/alerts/auto-rules/{monitor_id}",
        headers=_auth(user_token),
        params={"channel_ids": [channel_id]},
    )
    assert resp.status_code == 200
    rules = resp.json()
    assert len(rules) >= 1
    assert any(r["condition"] == "any_down" for r in rules)


@pytest.mark.asyncio
async def test_auto_rules_idempotent(client: AsyncClient, user_token: str) -> None:
    mon = await client.post(
        "/api/v1/monitors/",
        json={"name": "Idemp Mon", "url": "https://example.com"},
        headers=_auth(user_token),
    )
    monitor_id = mon.json()["id"]

    ch = await client.post(
        "/api/v1/alerts/channels",
        json={
            "name": "IdempCh",
            "type": "webhook",
            "config": {"url": "https://hooks.example.com/i"},
        },
        headers=_auth(user_token),
    )
    channel_id = ch.json()["id"]

    # First call creates rules
    r1 = await client.post(
        f"/api/v1/alerts/auto-rules/{monitor_id}",
        headers=_auth(user_token),
        params={"channel_ids": [channel_id]},
    )
    assert len(r1.json()) >= 1

    # Second call should create 0 (no duplicates)
    r2 = await client.post(
        f"/api/v1/alerts/auto-rules/{monitor_id}",
        headers=_auth(user_token),
        params={"channel_ids": [channel_id]},
    )
    assert len(r2.json()) == 0


@pytest.mark.asyncio
async def test_monitor_create_with_alert_channel_ids(client: AsyncClient, user_token: str) -> None:
    ch = await client.post(
        "/api/v1/alerts/channels",
        json={
            "name": "CreateCh",
            "type": "webhook",
            "config": {"url": "https://hooks.example.com/c"},
        },
        headers=_auth(user_token),
    )
    channel_id = ch.json()["id"]

    mon = await client.post(
        "/api/v1/monitors/",
        json={
            "name": "Mon With Alert",
            "url": "https://example.com",
            "alert_channel_ids": [channel_id],
        },
        headers=_auth(user_token),
    )
    assert mon.status_code == 201
    monitor_id = mon.json()["id"]

    # Verify rules were auto-created
    rules_resp = await client.get("/api/v1/alerts/rules", headers=_auth(user_token))
    all_rules = rules_resp.json()
    monitor_rules = [r for r in all_rules if r.get("monitor_id") == monitor_id]
    assert len(monitor_rules) >= 1
    assert any(r["condition"] == "any_down" for r in monitor_rules)


@pytest.mark.asyncio
async def test_threshold_suggestions_endpoint(client: AsyncClient, user_token: str) -> None:
    resp = await client.get(
        "/api/v1/alerts/suggestions/thresholds",
        headers=_auth(user_token),
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# ══════════════════════════════════════════════════════════════════════════════
# Correlation — Root cause tagging
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_common_cause_sets_root_cause(
    service_db: AsyncSession, test_user: User, test_probe: Probe
) -> None:
    """When incidents on 2 monitors correlate via probes, root_cause_monitor_id is set."""
    mon_a = Monitor(name="root-a", url="http://a.example.com", owner_id=test_user.id)
    mon_b = Monitor(name="root-b", url="http://b.example.com", owner_id=test_user.id)
    service_db.add_all([mon_a, mon_b])
    await service_db.flush()

    now = datetime.now(UTC)
    probe_ids = [str(test_probe.id)]

    # Create incident for mon_a first (started 30s ago)
    inc_a = Incident(
        monitor_id=mon_a.id,
        started_at=now - timedelta(seconds=30),
        scope=IncidentScope.global_,
        affected_probe_ids=probe_ids,
    )
    service_db.add(inc_a)
    await service_db.flush()

    # Create incident for mon_b (now)
    inc_b = Incident(
        monitor_id=mon_b.id,
        started_at=now,
        scope=IncidentScope.global_,
        affected_probe_ids=probe_ids,
    )
    service_db.add(inc_b)
    await service_db.flush()

    collector = _EventCollector()
    await _correlate_common_cause(service_db, inc_b, probe_ids, collector)

    assert inc_b.group_id is not None
    group = await service_db.get(IncidentGroup, inc_b.group_id)
    assert group is not None
    assert group.root_cause_monitor_id == mon_a.id
    assert group.correlation_type == "probe"


# ══════════════════════════════════════════════════════════════════════════════
# Correlation — Group-level
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_group_correlation_50pct(service_db: AsyncSession, test_user: User) -> None:
    """When >=50% of a group's monitors are down within 2min, they are grouped."""
    grp = MonitorGroup(name="infra-group", owner_id=test_user.id)
    service_db.add(grp)
    await service_db.flush()

    # Create 4 monitors in the group
    monitors = []
    for i in range(4):
        m = Monitor(
            name=f"grp-mon-{i}",
            url=f"http://m{i}.example.com",
            owner_id=test_user.id,
            group_id=grp.id,
        )
        service_db.add(m)
        monitors.append(m)
    await service_db.flush()

    now = datetime.now(UTC)

    # Open incidents on 2 out of 4 monitors (50% — should trigger)
    inc_0 = Incident(
        monitor_id=monitors[0].id,
        started_at=now - timedelta(seconds=30),
        scope=IncidentScope.global_,
        affected_probe_ids=[],
    )
    service_db.add(inc_0)
    await service_db.flush()

    inc_1 = Incident(
        monitor_id=monitors[1].id,
        started_at=now,
        scope=IncidentScope.global_,
        affected_probe_ids=[],
    )
    service_db.add(inc_1)
    await service_db.flush()

    collector = _EventCollector()
    await _correlate_by_group(service_db, inc_1, monitors[1], collector)

    assert inc_1.group_id is not None
    group = await service_db.get(IncidentGroup, inc_1.group_id)
    assert group is not None
    assert group.correlation_type == "group"
    assert group.root_cause_monitor_id == monitors[0].id


@pytest.mark.asyncio
async def test_group_correlation_below_threshold(service_db: AsyncSession, test_user: User) -> None:
    """When <50% of a group's monitors are down, no grouping occurs."""
    grp = MonitorGroup(name="sparse-group", owner_id=test_user.id)
    service_db.add(grp)
    await service_db.flush()

    monitors = []
    for i in range(6):
        m = Monitor(
            name=f"sparse-{i}",
            url=f"http://s{i}.example.com",
            owner_id=test_user.id,
            group_id=grp.id,
        )
        service_db.add(m)
        monitors.append(m)
    await service_db.flush()

    now = datetime.now(UTC)
    # Only 1 out of 6 down (<50%) — should NOT trigger
    inc = Incident(
        monitor_id=monitors[0].id,
        started_at=now,
        scope=IncidentScope.global_,
        affected_probe_ids=[],
    )
    service_db.add(inc)
    await service_db.flush()

    collector = _EventCollector()
    await _correlate_by_group(service_db, inc, monitors[0], collector)

    assert inc.group_id is None


# ══════════════════════════════════════════════════════════════════════════════
# Correlation — Dependency cascade
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_dependency_cascade_groups_parent_child(
    service_db: AsyncSession, test_user: User
) -> None:
    """Parent and child going down within 5min are grouped via dependency cascade."""
    parent = Monitor(name="dep-parent", url="http://parent.example.com", owner_id=test_user.id)
    child = Monitor(name="dep-child", url="http://child.example.com", owner_id=test_user.id)
    service_db.add_all([parent, child])
    await service_db.flush()

    dep = MonitorDependency(parent_id=parent.id, child_id=child.id, suppress_on_parent_down=True)
    service_db.add(dep)
    await service_db.flush()

    now = datetime.now(UTC)

    # Parent goes down first
    inc_parent = Incident(
        monitor_id=parent.id,
        started_at=now - timedelta(minutes=2),
        scope=IncidentScope.global_,
        affected_probe_ids=[],
    )
    service_db.add(inc_parent)
    await service_db.flush()

    # Child goes down 2 min later (within 5min window)
    inc_child = Incident(
        monitor_id=child.id,
        started_at=now,
        scope=IncidentScope.global_,
        affected_probe_ids=[],
    )
    service_db.add(inc_child)
    await service_db.flush()

    collector = _EventCollector()
    await _correlate_by_dependency(service_db, inc_child, child.id, collector)

    assert inc_child.group_id is not None
    group = await service_db.get(IncidentGroup, inc_child.group_id)
    assert group is not None
    assert group.correlation_type == "dependency"
    assert group.root_cause_monitor_id == parent.id


# ══════════════════════════════════════════════════════════════════════════════
# Pattern learning
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_pattern_learning_creates_entries(service_db: AsyncSession, test_user: User) -> None:
    """When incidents are grouped, CorrelationPattern entries are created."""
    mon_x = Monitor(name="pat-x", url="http://x.example.com", owner_id=test_user.id)
    mon_y = Monitor(name="pat-y", url="http://y.example.com", owner_id=test_user.id)
    service_db.add_all([mon_x, mon_y])
    await service_db.flush()

    now = datetime.now(UTC)
    group = IncidentGroup(
        triggered_at=now,
        cause_probe_ids=[],
        status="open",
        root_cause_monitor_id=mon_x.id,
        correlation_type="probe",
    )
    service_db.add(group)
    await service_db.flush()

    inc_x = Incident(
        monitor_id=mon_x.id,
        started_at=now,
        scope=IncidentScope.global_,
        affected_probe_ids=[],
        group_id=group.id,
    )
    inc_y = Incident(
        monitor_id=mon_y.id,
        started_at=now,
        scope=IncidentScope.global_,
        affected_probe_ids=[],
        group_id=group.id,
    )
    service_db.add_all([inc_x, inc_y])
    await service_db.flush()

    await update_patterns_for_group(service_db, group)

    patterns = (await service_db.execute(select(CorrelationPattern))).scalars().all()
    assert len(patterns) >= 1
    p = patterns[0]
    monitor_ids = {p.monitor_a_id, p.monitor_b_id}
    assert {mon_x.id, mon_y.id} == monitor_ids
    assert p.co_occurrence_count == 1


@pytest.mark.asyncio
async def test_pattern_learning_increments(service_db: AsyncSession, test_user: User) -> None:
    """Calling update_patterns_for_group twice increments co_occurrence_count."""
    mon_p = Monitor(name="pat-p", url="http://p.example.com", owner_id=test_user.id)
    mon_q = Monitor(name="pat-q", url="http://q.example.com", owner_id=test_user.id)
    service_db.add_all([mon_p, mon_q])
    await service_db.flush()

    now = datetime.now(UTC)
    prev_incidents = []
    for i in range(2):
        # Resolve previous incidents to avoid unique constraint on open incidents
        for inc in prev_incidents:
            inc.resolved_at = now
            inc.duration_seconds = 0
        if prev_incidents:
            await service_db.flush()
        prev_incidents = []

        group = IncidentGroup(
            triggered_at=now,
            cause_probe_ids=[],
            status="open",
            root_cause_monitor_id=mon_p.id,
            correlation_type="probe",
        )
        service_db.add(group)
        await service_db.flush()

        inc_p = Incident(
            monitor_id=mon_p.id,
            started_at=now,
            scope=IncidentScope.global_,
            affected_probe_ids=[],
            group_id=group.id,
        )
        inc_q = Incident(
            monitor_id=mon_q.id,
            started_at=now,
            scope=IncidentScope.global_,
            affected_probe_ids=[],
            group_id=group.id,
        )
        service_db.add_all([inc_p, inc_q])
        await service_db.flush()
        prev_incidents = [inc_p, inc_q]

        await update_patterns_for_group(service_db, group)

    # Should have count=2
    correlated = await get_correlated_monitors(service_db, mon_p.id, min_occurrences=1)
    assert len(correlated) >= 1
    assert correlated[0]["co_occurrence_count"] == 2


# ══════════════════════════════════════════════════════════════════════════════
# Correlated monitors endpoint
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_correlated_endpoint(client: AsyncClient, user_token: str) -> None:
    mon = await client.post(
        "/api/v1/monitors/",
        json={"name": "Corr Mon", "url": "https://example.com"},
        headers=_auth(user_token),
    )
    monitor_id = mon.json()["id"]

    resp = await client.get(
        f"/api/v1/monitors/{monitor_id}/correlated",
        headers=_auth(user_token),
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# ══════════════════════════════════════════════════════════════════════════════
# Incident group schema (root_cause fields)
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_incident_group_endpoint_has_root_cause(
    client: AsyncClient, admin_token: str
) -> None:
    resp = await client.get("/api/v1/incident-groups/", headers=_auth(admin_token))
    assert resp.status_code == 200
    # Schema should accept the new fields even if no groups exist yet
    data = resp.json()
    assert isinstance(data, list)
