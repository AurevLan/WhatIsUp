"""Tests for probe registration, heartbeat (with health), results, and stats."""

from __future__ import annotations

import json
import uuid

import bcrypt
import pytest
import pytest_asyncio
from fakeredis.aioredis import FakeRedis
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.models.probe import Probe

# Low-cost hash — bcrypt rounds=4 makes tests fast (~10ms vs ~200ms at rounds=12)
_PROBE_KEY = "wiu_test_probe_key_only_used_in_tests"
_PROBE_HEADERS = {"X-Probe-Api-Key": _PROBE_KEY}


@pytest_asyncio.fixture
async def probe_with_key(db_session: AsyncSession) -> Probe:
    """Active probe with a known API key (rounds=4 for speed)."""
    key_hash = bcrypt.hashpw(_PROBE_KEY.encode(), bcrypt.gensalt(rounds=4)).decode()
    probe = Probe(name="auth-probe", location_name="Test DC", api_key_hash=key_hash)
    db_session.add(probe)
    await db_session.flush()
    return probe


# ── Registration ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_probe_register(client: AsyncClient, admin_token: str) -> None:
    resp = await client.post(
        "/api/v1/probes/register",
        json={"name": "paris-probe-01", "location_name": "Paris — OVH"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "paris-probe-01"
    assert data["location_name"] == "Paris — OVH"
    assert "api_key" in data
    assert data["api_key"].startswith("wiu_")
    assert data["is_active"] is True


@pytest.mark.asyncio
async def test_probe_register_requires_superadmin(client: AsyncClient, user_token: str) -> None:
    resp = await client.post(
        "/api/v1/probes/register",
        json={"name": "sneaky-probe", "location_name": "Somewhere"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_probe_register_requires_auth(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/probes/register",
        json={"name": "no-auth-probe", "location_name": "Nowhere"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_probe_register_duplicate_name(client: AsyncClient, admin_token: str) -> None:
    headers = {"Authorization": f"Bearer {admin_token}"}
    await client.post(
        "/api/v1/probes/register",
        json={"name": "dup-probe", "location_name": "Lyon"},
        headers=headers,
    )
    resp = await client.post(
        "/api/v1/probes/register",
        json={"name": "dup-probe", "location_name": "Marseille"},
        headers=headers,
    )
    assert resp.status_code == 409


# ── Heartbeat ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_probe_heartbeat_with_health(
    client: AsyncClient, probe_with_key: Probe, fake_redis: FakeRedis
) -> None:
    health_payload = {
        "cpu_percent": 23.5,
        "ram_percent": 67.2,
        "disk_percent": 45.0,
        "load_avg_1m": 1.23,
        "monitors_active": 10,
        "checks_running": 2,
    }
    resp = await client.post(
        "/api/v1/probes/heartbeat",
        json={"health": health_payload},
        headers=_PROBE_HEADERS,
    )
    assert resp.status_code == 200
    assert "monitors" in resp.json()

    # Health must be stored in Redis with a TTL
    stored = await fake_redis.get(f"whatisup:probe_health:{probe_with_key.id}")
    assert stored is not None
    stored_data = json.loads(stored)
    assert stored_data["cpu_percent"] == 23.5
    assert stored_data["monitors_active"] == 10
    ttl = await fake_redis.ttl(f"whatisup:probe_health:{probe_with_key.id}")
    assert ttl > 0


@pytest.mark.asyncio
async def test_probe_heartbeat_without_health(
    client: AsyncClient, probe_with_key: Probe, fake_redis: FakeRedis
) -> None:
    """Heartbeat without health payload is accepted (backwards compat)."""
    resp = await client.post(
        "/api/v1/probes/heartbeat",
        json={},
        headers=_PROBE_HEADERS,
    )
    assert resp.status_code == 200
    assert "monitors" in resp.json()
    # No health data stored
    stored = await fake_redis.get(f"whatisup:probe_health:{probe_with_key.id}")
    assert stored is None


@pytest.mark.asyncio
async def test_probe_heartbeat_invalid_key(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/probes/heartbeat",
        json={},
        headers={"X-Probe-Api-Key": "wiu_totally_invalid_key_xxx"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_probe_heartbeat_bad_prefix(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/probes/heartbeat",
        json={},
        headers={"X-Probe-Api-Key": "badprefix_key"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_probe_heartbeat_health_field_validation(
    client: AsyncClient, probe_with_key: Probe
) -> None:
    """Health fields outside valid ranges must be rejected."""
    resp = await client.post(
        "/api/v1/probes/heartbeat",
        json={"health": {"cpu_percent": 150.0}},  # >100 is invalid
        headers=_PROBE_HEADERS,
    )
    assert resp.status_code == 422


# ── Push result ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_probe_push_result_unknown_monitor(
    client: AsyncClient, probe_with_key: Probe
) -> None:
    resp = await client.post(
        "/api/v1/probes/results",
        json={
            "monitor_id": str(uuid.uuid4()),
            "checked_at": "2025-01-01T00:00:00Z",
            "status": "up",
        },
        headers=_PROBE_HEADERS,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_probe_push_result_no_key(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/probes/results",
        json={
            "monitor_id": str(uuid.uuid4()),
            "checked_at": "2025-01-01T00:00:00Z",
            "status": "up",
        },
    )
    assert resp.status_code == 422  # Missing required header


# ── Stats ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_probe_stats_requires_superadmin(client: AsyncClient, user_token: str) -> None:
    resp = await client.get(
        "/api/v1/probes/stats",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_probe_stats_returns_list(client: AsyncClient, admin_token: str) -> None:
    resp = await client.get(
        "/api/v1/probes/stats",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_probe_stats_includes_health_from_redis(
    client: AsyncClient,
    admin_token: str,
    probe_with_key: Probe,
    fake_redis: FakeRedis,
) -> None:
    """GET /probes/stats enriches probes with health data stored in Redis."""
    health = {
        "cpu_percent": 42.0,
        "ram_percent": 55.0,
        "disk_percent": 30.0,
        "load_avg_1m": 0.8,
        "monitors_active": 5,
        "checks_running": 1,
    }
    await fake_redis.set(
        f"whatisup:probe_health:{probe_with_key.id}",
        json.dumps(health),
        ex=120,
    )

    resp = await client.get(
        "/api/v1/probes/stats",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    probes = resp.json()
    our = next((p for p in probes if p["id"] == str(probe_with_key.id)), None)
    assert our is not None
    assert our["health"] is not None
    assert our["health"]["cpu_percent"] == 42.0
    assert our["health"]["monitors_active"] == 5
    assert our["health"]["checks_running"] == 1


@pytest.mark.asyncio
async def test_probe_stats_health_none_when_stale(
    client: AsyncClient,
    admin_token: str,
    probe_with_key: Probe,
    fake_redis: FakeRedis,
) -> None:
    """Probe health is None when no Redis entry exists (stale / probe offline)."""
    # Ensure no health key in Redis
    await fake_redis.delete(f"whatisup:probe_health:{probe_with_key.id}")

    resp = await client.get(
        "/api/v1/probes/stats",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    probes = resp.json()
    our = next((p for p in probes if p["id"] == str(probe_with_key.id)), None)
    assert our is not None
    assert our["health"] is None


# ── List / Get / Update / Delete ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_probe_list_superadmin(client: AsyncClient, admin_token: str) -> None:
    resp = await client.get(
        "/api/v1/probes/",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_probe_toggle_active(
    client: AsyncClient, admin_token: str, probe_with_key: Probe
) -> None:
    headers = {"Authorization": f"Bearer {admin_token}"}
    resp = await client.patch(
        f"/api/v1/probes/{probe_with_key.id}",
        json={"is_active": False},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False

    # Re-enable
    resp = await client.patch(
        f"/api/v1/probes/{probe_with_key.id}",
        json={"is_active": True},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["is_active"] is True


# ── Probe incident timeline (T4) ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_probe_incident_timeline_empty_when_no_incidents(
    client: AsyncClient, admin_token: str, probe_with_key: Probe
) -> None:
    """A fresh probe with no recorded incidents returns an empty timeline."""
    resp = await client.get(
        f"/api/v1/probes/{probe_with_key.id}/incident-timeline",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_probe_incident_timeline_groups_by_monitor(
    client: AsyncClient,
    db_session: AsyncSession,
    admin_token: str,
    admin_user,
    probe_with_key: Probe,
) -> None:
    """Two incidents on the same monitor appear once with two incident entries."""
    from datetime import UTC, datetime, timedelta

    from whatisup.models.incident import Incident, IncidentScope
    from whatisup.models.monitor import Monitor

    monitor = Monitor(name="mon-t4", url="http://example.com", owner_id=admin_user.id)
    db_session.add(monitor)
    await db_session.flush()

    now = datetime.now(UTC)
    inc_old = Incident(
        monitor_id=monitor.id,
        started_at=now - timedelta(days=3),
        resolved_at=now - timedelta(days=3, hours=-1),
        duration_seconds=3600,
        scope=IncidentScope.global_,
        affected_probe_ids=[str(probe_with_key.id)],
    )
    inc_recent = Incident(
        monitor_id=monitor.id,
        started_at=now - timedelta(hours=2),
        scope=IncidentScope.global_,
        affected_probe_ids=[str(probe_with_key.id)],
    )
    db_session.add_all([inc_old, inc_recent])
    await db_session.flush()

    resp = await client.get(
        f"/api/v1/probes/{probe_with_key.id}/incident-timeline",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    entry = data[0]
    assert entry["monitor_name"] == "mon-t4"
    assert entry["monitor_url"] == "http://example.com"
    assert len(entry["incidents"]) == 2
    # Sorted DESC by started_at — newest incident first.
    assert entry["incidents"][0]["resolved_at"] is None
    assert entry["incidents"][1]["duration_seconds"] == 3600


@pytest.mark.asyncio
async def test_probe_incident_timeline_filters_by_window(
    client: AsyncClient,
    db_session: AsyncSession,
    admin_token: str,
    admin_user,
    probe_with_key: Probe,
) -> None:
    """Incidents older than `days` are excluded from the timeline."""
    from datetime import UTC, datetime, timedelta

    from whatisup.models.incident import Incident, IncidentScope
    from whatisup.models.monitor import Monitor

    monitor = Monitor(name="mon-t4-window", url="http://example.com", owner_id=admin_user.id)
    db_session.add(monitor)
    await db_session.flush()

    now = datetime.now(UTC)
    inc_outside = Incident(
        monitor_id=monitor.id,
        started_at=now - timedelta(days=30),
        scope=IncidentScope.global_,
        affected_probe_ids=[str(probe_with_key.id)],
    )
    inc_inside = Incident(
        monitor_id=monitor.id,
        started_at=now - timedelta(hours=2),
        scope=IncidentScope.global_,
        affected_probe_ids=[str(probe_with_key.id)],
    )
    db_session.add_all([inc_outside, inc_inside])
    await db_session.flush()

    # days=7 should exclude the 30-day-old incident
    resp = await client.get(
        f"/api/v1/probes/{probe_with_key.id}/incident-timeline?days=7",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert len(data[0]["incidents"]) == 1


@pytest.mark.asyncio
async def test_probe_incident_timeline_excludes_other_probes(
    client: AsyncClient,
    db_session: AsyncSession,
    admin_token: str,
    admin_user,
    probe_with_key: Probe,
) -> None:
    """Incidents that don't reference this probe's id are not surfaced."""
    from datetime import UTC, datetime, timedelta

    from whatisup.models.incident import Incident, IncidentScope
    from whatisup.models.monitor import Monitor

    other_probe = Probe(name="other", location_name="Elsewhere", api_key_hash="x")
    db_session.add(other_probe)
    await db_session.flush()

    monitor = Monitor(name="mon-other", url="http://example.com", owner_id=admin_user.id)
    db_session.add(monitor)
    await db_session.flush()

    db_session.add(
        Incident(
            monitor_id=monitor.id,
            started_at=datetime.now(UTC) - timedelta(hours=1),
            scope=IncidentScope.global_,
            affected_probe_ids=[str(other_probe.id)],  # not our probe
        )
    )
    await db_session.flush()

    resp = await client.get(
        f"/api/v1/probes/{probe_with_key.id}/incident-timeline",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_probe_incident_timeline_404_on_unknown_probe(
    client: AsyncClient, admin_token: str
) -> None:
    resp = await client.get(
        f"/api/v1/probes/{uuid.uuid4()}/incident-timeline",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_probe_incident_timeline_requires_superadmin(
    client: AsyncClient, user_token: str, probe_with_key: Probe
) -> None:
    """Non-superadmin users get 403."""
    resp = await client.get(
        f"/api/v1/probes/{probe_with_key.id}/incident-timeline",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 403


# ── Parité des schémas de sortie ──────────────────────────────────────────────


def test_probe_stats_out_is_a_superset_of_probe_out() -> None:
    """``/probes/stats`` is documented as the *enriched* view, so it must expose
    everything the basic list does.

    It used to be a parallel model, and four fields added to ``ProbeOut`` after
    it was written were never mirrored — FastAPI then dropped them from the
    response without a word. Because ``/stats`` is the superadmin path, the
    agent version was invisible to exactly the people administering the fleet.
    This guard fails the day the two drift again.
    """
    from whatisup.schemas.probe import ProbeOut, ProbeStatsOut

    missing = set(ProbeOut.model_fields) - set(ProbeStatsOut.model_fields)
    assert not missing, f"ProbeStatsOut ne réexpose pas : {sorted(missing)}"


@pytest.mark.asyncio
async def test_probe_stats_exposes_agent_version(
    client: AsyncClient, admin_token: str, db_session: AsyncSession
) -> None:
    """The regression this lot fixes: a probe reporting its version showed as
    "unknown" in the UI for superadmins, because ``/stats`` never carried the
    field."""
    probe = Probe(
        name="versioned-probe",
        location_name="Paris",
        api_key_hash="x",
        version="1.27.0",
    )
    db_session.add(probe)
    await db_session.flush()
    await db_session.commit()

    resp = await client.get(
        "/api/v1/probes/stats",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    row = next(p for p in resp.json() if p["name"] == "versioned-probe")
    assert row["version"] == "1.27.0"
