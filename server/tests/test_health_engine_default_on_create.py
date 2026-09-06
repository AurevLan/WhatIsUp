"""V2 Global Health Engine, plan Cap v2 4a.

Monitors created through the API now default to ``health_engine_enabled=True``
with a matching default ``SLORule`` (``min_probes=1``) so the fleet consensus
is never blind for a fresh, single-probe install. See CLAUDE.md "Health
Engine V2 — ops prod" for the operational pitfall this guards against
(engine active + zero active rule = a silently mute monitor), and
``services/health.evaluate_slos`` for the filet covering paths other than
creation (manual toggle, rule deletion).
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.models.incident import Incident
from whatisup.models.monitor import Monitor
from whatisup.models.probe import Probe
from whatisup.models.result import CheckResult, CheckStatus
from whatisup.models.user import User
from whatisup.services import health
from whatisup.services.incident import process_check_result


@pytest.mark.asyncio
async def test_create_monitor_enables_health_engine_with_default_rule(
    client: AsyncClient, user_token: str
) -> None:
    """A monitor created via POST /monitors gets the engine active and an
    auto-provisioned default quorum_down rule — the contract of this lot."""
    resp = await client.post(
        "/api/v1/monitors/",
        json={"name": "New Monitor", "url": "https://example.com"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["health_engine_enabled"] is True

    rules_resp = await client.get(
        f"/api/v1/monitors/{body['id']}/slo-rules",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert rules_resp.status_code == 200
    rules = rules_resp.json()
    assert len(rules) == 1
    rule = rules[0]
    assert rule["rule_type"] == "quorum_down"
    assert rule["enabled"] is True
    # The one deliberate divergence from DEFAULT_RULE_KWARGS (min_probes=2):
    # at 1 probe this behaves exactly like the legacy per-probe decider, and
    # the consensus takes over on its own once a second probe reports.
    assert rule["min_probes"] == 1
    assert rule["quorum_ratio"] == 0.6
    assert rule["window_seconds"] == 300
    assert rule["cooldown_seconds"] == 60


@pytest.mark.asyncio
async def test_create_monitor_with_engine_explicitly_disabled_gets_no_rule(
    client: AsyncClient, user_token: str
) -> None:
    """An explicit opt-out at creation must not get a rule provisioned —
    the auto-provisioning is conditional on the engine actually being on."""
    resp = await client.post(
        "/api/v1/monitors/",
        json={
            "name": "Legacy Monitor",
            "url": "https://legacy.example.com",
            "health_engine_enabled": False,
        },
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["health_engine_enabled"] is False

    rules_resp = await client.get(
        f"/api/v1/monitors/{body['id']}/slo-rules",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert rules_resp.status_code == 200
    assert rules_resp.json() == []


@pytest.mark.asyncio
async def test_single_probe_down_opens_incident_on_freshly_created_monitor(
    client: AsyncClient,
    user_token: str,
    db_session: AsyncSession,
) -> None:
    """The regression this lot forbids forever: a fresh install running only
    the embedded probe must still detect an outage. min_probes=1 is what
    makes that true for a monitor that gets the Health Engine by default —
    pinned end to end here, from API creation through to an opened incident
    with a single reporting probe."""
    create = await client.post(
        "/api/v1/monitors/",
        json={"name": "Solo Probe Monitor", "url": "https://solo.example.com"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert create.status_code == 201
    body = create.json()
    assert body["health_engine_enabled"] is True
    monitor_id = uuid.UUID(body["id"])

    probe = Probe(name="probe-solo", location_name="Paris", api_key_hash="x")
    db_session.add(probe)
    await db_session.flush()

    monitor = (
        await db_session.execute(select(Monitor).where(Monitor.id == monitor_id))
    ).scalar_one()

    async def publish(_event):
        return None

    cr = CheckResult(
        monitor_id=monitor.id,
        probe_id=probe.id,
        status=CheckStatus.down,
        response_time_ms=None,
        checked_at=datetime.now(UTC),
    )
    db_session.add(cr)
    await db_session.flush()
    # Mirrors the real background flow (probes.py): legacy decider first
    # (bridges away immediately since health_engine_enabled=True), then the
    # health-engine ingest that actually evaluates the SLO rule.
    await process_check_result(db_session, cr, publish)
    await health.ingest(db_session, cr, publish_event=publish)

    incidents = (
        (await db_session.execute(select(Incident).where(Incident.monitor_id == monitor.id)))
        .scalars()
        .all()
    )
    assert len(incidents) == 1
    assert incidents[0].slo_rule_id is not None
    assert incidents[0].trigger_kind == "quorum_down"
    assert incidents[0].resolved_at is None


@pytest.mark.asyncio
async def test_existing_monitor_with_engine_disabled_keeps_legacy_path(
    service_db: AsyncSession,
    test_user: User,
    test_probe: Probe,
) -> None:
    """A monitor whose stored ``health_engine_enabled`` is False (the
    pre-4a state of every monitor created before this change) must not be
    flipped by the new default — nothing here migrates existing rows."""
    monitor = Monitor(
        name="mon-preexisting-legacy",
        url="http://legacy-existing.test",
        owner_id=test_user.id,
        health_engine_enabled=False,
    )
    service_db.add(monitor)
    await service_db.flush()

    async def publish(_event):
        return None

    cr = CheckResult(
        monitor_id=monitor.id,
        probe_id=test_probe.id,
        status=CheckStatus.down,
        response_time_ms=None,
        checked_at=datetime.now(UTC),
    )
    service_db.add(cr)
    await service_db.flush()
    await process_check_result(service_db, cr, publish)

    incidents = (
        (await service_db.execute(select(Incident).where(Incident.monitor_id == monitor.id)))
        .scalars()
        .all()
    )
    assert len(incidents) == 1
    assert incidents[0].slo_rule_id is None
    assert incidents[0].trigger_kind == "legacy"


@pytest.mark.asyncio
async def test_engine_enabled_with_no_active_rule_is_visible_not_silent(
    service_db: AsyncSession,
    test_user: User,
    test_probe: Probe,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The state creation now prevents is still reachable another way — a
    manual toggle, or deleting the last SLORule. It must not be silent: no
    incident opens, but a structured warning is logged so it's diagnosable
    (CLAUDE.md "Health Engine V2" pitfall #1)."""
    monitor = Monitor(
        name="mon-mute",
        url="http://mute.test",
        owner_id=test_user.id,
        health_engine_enabled=True,
    )
    service_db.add(monitor)
    await service_db.flush()
    # Deliberately no SLORule added — this is the state under test.

    async def publish(_event):
        return None

    cr = CheckResult(
        monitor_id=monitor.id,
        probe_id=test_probe.id,
        status=CheckStatus.down,
        response_time_ms=None,
        checked_at=datetime.now(UTC),
    )
    service_db.add(cr)
    await service_db.flush()

    with caplog.at_level(logging.WARNING):
        await process_check_result(service_db, cr, publish)
        await health.ingest(service_db, cr, publish_event=publish)

    assert "health_engine_no_active_rule" in caplog.text

    incidents = (
        (await service_db.execute(select(Incident).where(Incident.monitor_id == monitor.id)))
        .scalars()
        .all()
    )
    assert incidents == []
