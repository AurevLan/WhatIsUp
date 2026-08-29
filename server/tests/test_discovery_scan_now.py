"""Discovery scan-now — feedback loop (plan E, E-1).

``POST /discovery/sources/{id}/scan-now`` mirrors ``POST
/monitors/{id}/trigger-check`` exactly: a Redis flag consumed by the probe's
own heartbeat and turned into an out-of-cycle run of the same job. Same
visibility gate as the other discovery mutations (``_get_visible_source``,
editor role minimum) — a viewer must not be able to trigger a scan tool.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from fakeredis.aioredis import FakeRedis
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.core.limiter import limiter
from whatisup.core.security import hash_password
from whatisup.models.discovery import DiscoverySource
from whatisup.models.team import TeamMembership, TeamRole
from whatisup.models.user import User

TEST_PASSWORD = "TestPassword123!"


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def stranger(db_session: AsyncSession) -> User:
    u = User(
        email="scan-now-stranger@test.com",
        username="scan-now-stranger",
        hashed_password=hash_password(TEST_PASSWORD),
        is_superadmin=False,
        can_create_monitors=True,
    )
    db_session.add(u)
    await db_session.flush()
    return u


@pytest_asyncio.fixture
async def stranger_token(client: AsyncClient, stranger: User) -> str:
    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": stranger.email, "password": TEST_PASSWORD},
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]


async def _register_probe(
    client: AsyncClient, admin_token: str, name: str = "probe-scan-now"
) -> str:
    """Register a probe visible to every non-superadmin user of the test.

    Targeting a probe with a discovery source needs the same visibility
    ``GET /probes/`` enforces (``assert_can_use_probe``), so a probe in no
    group cannot be targeted by a regular user — see ``test_discovery.py``.
    """
    resp = await client.post(
        "/api/v1/probes/register",
        json={"name": name, "location_name": "Paris"},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 201, resp.text
    probe_id = resp.json()["id"]

    users = await client.get("/api/v1/admin/users", headers=_auth(admin_token))
    assert users.status_code == 200, users.text
    user_ids = [u["id"] for u in users.json() if not u["is_superadmin"]]
    if user_ids:
        grp = await client.post(
            "/api/v1/admin/probe-groups",
            json={"name": f"grp-{probe_id[:8]}"},
            headers=_auth(admin_token),
        )
        assert grp.status_code == 201, grp.text
        group_id = grp.json()["id"]
        await client.post(
            f"/api/v1/admin/probe-groups/{group_id}/probes",
            json={"probe_ids": [probe_id]},
            headers=_auth(admin_token),
        )
        await client.post(
            f"/api/v1/admin/probe-groups/{group_id}/users",
            json={"user_ids": user_ids},
            headers=_auth(admin_token),
        )
    return probe_id


@pytest_asyncio.fixture
async def owned_source(
    db_session: AsyncSession, regular_user: User, admin_token: str, client: AsyncClient
) -> DiscoverySource:
    probe_id = await _register_probe(client, admin_token)
    source = DiscoverySource(
        owner_id=regular_user.id,
        probe_id=uuid.UUID(probe_id),
        source_type="docker",
        params={},
    )
    db_session.add(source)
    await db_session.flush()
    await db_session.commit()
    return source


# ── Success ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_scan_now_queues_and_returns_202(
    client: AsyncClient, user_token: str, owned_source: DiscoverySource
) -> None:
    resp = await client.post(
        f"/api/v1/discovery/sources/{owned_source.id}/scan-now", headers=_auth(user_token)
    )
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["status"] == "queued"
    assert body["source_id"] == str(owned_source.id)


@pytest.mark.asyncio
async def test_scan_now_sets_redis_trigger_flag(
    client: AsyncClient,
    user_token: str,
    owned_source: DiscoverySource,
    fake_redis: FakeRedis,
) -> None:
    resp = await client.post(
        f"/api/v1/discovery/sources/{owned_source.id}/scan-now", headers=_auth(user_token)
    )
    assert resp.status_code == 202

    value = await fake_redis.get(f"whatisup:discovery_trigger:{owned_source.id}")
    assert value is not None


@pytest.mark.asyncio
async def test_scan_now_flag_surfaces_on_next_heartbeat_and_is_consumed(
    client: AsyncClient,
    user_token: str,
    admin_token: str,
    db_session: AsyncSession,
    owned_source: DiscoverySource,
) -> None:
    """End-to-end wiring: scan-now sets the flag, the probe's own heartbeat
    (authenticated with its real key, not the owner's JWT) sees
    `trigger_now: true` on its source, and a second heartbeat no longer does —
    the same one-shot semantics as the monitor trigger-check flag."""
    import bcrypt

    from whatisup.models.probe import Probe

    api_key = "wiu_test_scan_now_probe_key"
    probe = Probe(
        name="scan-now-heartbeat-probe",
        location_name="Paris",
        api_key_hash=bcrypt.hashpw(api_key.encode(), bcrypt.gensalt(rounds=4)).decode(),
    )
    db_session.add(probe)
    await db_session.flush()
    owned_source.probe_id = probe.id
    await db_session.flush()
    await db_session.commit()

    resp = await client.post(
        f"/api/v1/discovery/sources/{owned_source.id}/scan-now", headers=_auth(user_token)
    )
    assert resp.status_code == 202

    hb1 = await client.post(
        "/api/v1/probes/heartbeat", json={}, headers={"X-Probe-Api-Key": api_key}
    )
    assert hb1.status_code == 200
    sources = hb1.json()["discovery_sources"]
    assert len(sources) == 1
    assert sources[0]["trigger_now"] is True

    hb2 = await client.post(
        "/api/v1/probes/heartbeat", json={}, headers={"X-Probe-Api-Key": api_key}
    )
    assert hb2.status_code == 200
    assert hb2.json()["discovery_sources"][0]["trigger_now"] is False


# ── Visibility ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_scan_now_cross_tenant_refused(
    client: AsyncClient, stranger_token: str, owned_source: DiscoverySource
) -> None:
    resp = await client.post(
        f"/api/v1/discovery/sources/{owned_source.id}/scan-now", headers=_auth(stranger_token)
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_scan_now_unknown_source_404(client: AsyncClient, user_token: str) -> None:
    resp = await client.post(
        f"/api/v1/discovery/sources/{uuid.uuid4()}/scan-now", headers=_auth(user_token)
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_scan_now_viewer_role_insufficient(
    client: AsyncClient,
    user_token: str,
    stranger_token: str,
    stranger: User,
    db_session: AsyncSession,
    admin_token: str,
    regular_user: User,
) -> None:
    """A team viewer may see a source but scan-now requires editor+ (same
    `min_role` as `update_source`/`accept`/`dismiss`)."""
    probe_id = await _register_probe(client, admin_token, "probe-scan-now-viewer")
    team_resp = await client.post(
        "/api/v1/teams/",
        json={"name": "Scan Now Team", "slug": "scan-now-team"},
        headers=_auth(user_token),
    )
    assert team_resp.status_code == 201
    team_id = team_resp.json()["id"]
    db_session.add(
        TeamMembership(user_id=stranger.id, team_id=uuid.UUID(team_id), role=TeamRole.viewer)
    )
    await db_session.flush()
    await db_session.commit()

    resp = await client.post(
        "/api/v1/discovery/sources/",
        json={"probe_id": probe_id, "source_type": "docker", "params": {}, "team_id": team_id},
        headers=_auth(user_token),
    )
    assert resp.status_code == 201, resp.text
    source_id = resp.json()["id"]

    resp = await client.post(
        f"/api/v1/discovery/sources/{source_id}/scan-now", headers=_auth(stranger_token)
    )
    assert resp.status_code == 403


# ── Rate limit gate ──────────────────────────────────────────────────────────


def test_scan_now_is_rate_limited() -> None:
    key = "whatisup.api.v1.discovery.scan_source_now"
    assert key in limiter._route_limits or key in limiter._dynamic_route_limits
