"""Probe trust hardening (A2): cross-monitor forge guard (H2) + key rotation (H1).

H2 — ``POST /probes/results`` must reject a result for a monitor the probe does
not serve. The only probe↔monitor "assignment" the system models is
``Monitor.network_scope`` (matched against ``Probe.network_type`` at heartbeat);
scope ``all`` stays served by every probe.

H1 — ``POST /probes/{id}/rotate-key`` issues a new key, returns it once, and
invalidates the Redis auth cache so the previous key stops working immediately.
"""

from __future__ import annotations

import bcrypt
import pytest
import pytest_asyncio
from fakeredis.aioredis import FakeRedis
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.models.audit_log import AuditLog
from whatisup.models.monitor import Monitor
from whatisup.models.probe import NetworkType, Probe
from whatisup.models.user import User

_PROBE_KEY = "wiu_trust_probe_key_for_tests_only"
_PROBE_HEADERS = {"X-Probe-Api-Key": _PROBE_KEY}

_INTERNAL_PROBE_KEY = "wiu_trust_internal_probe_key_tests"
_INTERNAL_PROBE_HEADERS = {"X-Probe-Api-Key": _INTERNAL_PROBE_KEY}


@pytest_asyncio.fixture
async def external_probe(db_session: AsyncSession) -> Probe:
    """Active external probe with a known API key (bcrypt rounds=4 for speed)."""
    key_hash = bcrypt.hashpw(_PROBE_KEY.encode(), bcrypt.gensalt(rounds=4)).decode()
    probe = Probe(
        name="trust-probe",
        location_name="Test DC",
        api_key_hash=key_hash,
        network_type=NetworkType.external,
    )
    db_session.add(probe)
    await db_session.flush()
    return probe


@pytest_asyncio.fixture
async def internal_probe(db_session: AsyncSession) -> Probe:
    """Active internal probe with its own known API key (bcrypt rounds=4)."""
    key_hash = bcrypt.hashpw(_INTERNAL_PROBE_KEY.encode(), bcrypt.gensalt(rounds=4)).decode()
    probe = Probe(
        name="trust-probe-internal",
        location_name="Internal DC",
        api_key_hash=key_hash,
        network_type=NetworkType.internal,
    )
    db_session.add(probe)
    await db_session.flush()
    return probe


@pytest_asyncio.fixture
async def monitor_owner(db_session: AsyncSession) -> User:
    u = User(
        email="mon-owner@test.com",
        username="mon-owner",
        hashed_password="x",
        can_create_monitors=True,
    )
    db_session.add(u)
    await db_session.flush()
    return u


async def _make_monitor(
    db_session: AsyncSession, owner: User, scope: str, check_type: str = "http"
) -> Monitor:
    m = Monitor(
        name=f"mon-{scope}-{check_type}",
        url="http://example.com",
        owner_id=owner.id,
        network_scope=scope,
        check_type=check_type,
    )
    db_session.add(m)
    await db_session.flush()
    return m


def _result_body(monitor_id) -> dict:
    return {
        "monitor_id": str(monitor_id),
        "checked_at": "2025-01-01T00:00:00Z",
        "status": "up",
    }


@pytest_asyncio.fixture
def stub_bg_processing(db_session, monkeypatch):
    """Redirect the /results background task at the shared test session.

    ``push_result`` schedules ``_process`` which opens a *fresh* session via
    ``get_session_factory()`` and reloads the just-committed row. The real
    factory points at a different DB in tests, so we redirect it to the test
    session (which already holds the row) and stub the heavy pipeline calls —
    we only care that the endpoint accepts the result, not the downstream
    incident/health processing (covered by their own tests).
    """
    import whatisup.api.v1.probes as probes_mod
    import whatisup.core.database as dbmod
    import whatisup.services.health as health_mod

    class _Ctx:
        async def __aenter__(self):
            return db_session

        async def __aexit__(self, *exc):
            return False

    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr(dbmod, "get_session_factory", lambda: lambda: _Ctx())
    monkeypatch.setattr(probes_mod, "process_check_result", _noop)
    monkeypatch.setattr(health_mod, "ingest", _noop)
    return db_session


# ── H2 — cross-monitor forge guard ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_forge_result_for_unserved_monitor_is_forbidden(
    client: AsyncClient, external_probe: Probe, monitor_owner: User, db_session: AsyncSession
) -> None:
    """External probe forging a result for an internal-scoped monitor → 403."""
    monitor = await _make_monitor(db_session, monitor_owner, scope="internal")
    resp = await client.post(
        "/api/v1/probes/results", json=_result_body(monitor.id), headers=_PROBE_HEADERS
    )
    assert resp.status_code == 403, resp.text
    assert "network scope" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_result_for_matching_scope_is_accepted(
    client: AsyncClient,
    external_probe: Probe,
    monitor_owner: User,
    db_session: AsyncSession,
    stub_bg_processing,
) -> None:
    """External probe reporting on an external-scoped monitor → accepted."""
    monitor = await _make_monitor(db_session, monitor_owner, scope="external")
    resp = await client.post(
        "/api/v1/probes/results", json=_result_body(monitor.id), headers=_PROBE_HEADERS
    )
    assert resp.status_code == 202, resp.text


@pytest.mark.asyncio
async def test_result_for_scope_all_is_accepted(
    client: AsyncClient,
    external_probe: Probe,
    monitor_owner: User,
    db_session: AsyncSession,
    stub_bg_processing,
) -> None:
    """Monitor with scope 'all' stays served by every probe (permissive default)."""
    monitor = await _make_monitor(db_session, monitor_owner, scope="all")
    resp = await client.post(
        "/api/v1/probes/results", json=_result_body(monitor.id), headers=_PROBE_HEADERS
    )
    assert resp.status_code == 202, resp.text


@pytest.mark.asyncio
async def test_forge_result_reverse_direction_is_forbidden(
    client: AsyncClient, internal_probe: Probe, monitor_owner: User, db_session: AsyncSession
) -> None:
    """Internal probe forging a result for an external-scoped monitor → 403.

    Guards the opposite scope direction from the primary forge test — a probe on
    one network must not be able to report on a monitor pinned to the other.
    """
    monitor = await _make_monitor(db_session, monitor_owner, scope="external")
    resp = await client.post(
        "/api/v1/probes/results",
        json=_result_body(monitor.id),
        headers=_INTERNAL_PROBE_HEADERS,
    )
    assert resp.status_code == 403, resp.text
    assert "network scope" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_forge_result_for_composite_monitor_is_forbidden(
    client: AsyncClient, external_probe: Probe, monitor_owner: User, db_session: AsyncSession
) -> None:
    """Composite monitors are never distributed to probes → any result is a forge → 403.

    Even with the permissive scope 'all', a composite monitor has no physical
    check and is filtered out of the heartbeat config, so no legitimate probe
    result exists for it.
    """
    monitor = await _make_monitor(db_session, monitor_owner, scope="all", check_type="composite")
    resp = await client.post(
        "/api/v1/probes/results", json=_result_body(monitor.id), headers=_PROBE_HEADERS
    )
    assert resp.status_code == 403, resp.text


# ── H1 — probe API key rotation ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rotate_key_invalidates_old_key_immediately(
    client: AsyncClient,
    external_probe: Probe,
    admin_token: str,
    fake_redis: FakeRedis,
) -> None:
    """After rotation the old key is refused at once (cache evicted); new works."""
    # 1. Warm the auth cache with the old key via a heartbeat.
    hb1 = await client.post("/api/v1/probes/heartbeat", json={}, headers=_PROBE_HEADERS)
    assert hb1.status_code == 200
    digest_forward = await fake_redis.get(f"whatisup:probe_auth_rev:{external_probe.id}")
    assert digest_forward is not None  # reverse index written

    # 2. Rotate the key (superadmin).
    rot = await client.post(
        f"/api/v1/probes/{external_probe.id}/rotate-key",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert rot.status_code == 200, rot.text
    new_key = rot.json()["api_key"]
    assert new_key.startswith("wiu_")
    assert new_key != _PROBE_KEY

    # Cache entry for the old key must be gone (evicted, not just TTL-expired).
    assert await fake_redis.get(f"whatisup:probe_auth_rev:{external_probe.id}") is None

    # 3. Old key must now be rejected (no stale fast-path acceptance).
    old = await client.post("/api/v1/probes/heartbeat", json={}, headers=_PROBE_HEADERS)
    assert old.status_code == 401, old.text

    # 4. New key is accepted.
    new = await client.post(
        "/api/v1/probes/heartbeat", json={}, headers={"X-Probe-Api-Key": new_key}
    )
    assert new.status_code == 200, new.text


@pytest.mark.asyncio
async def test_rotate_key_requires_superadmin(
    client: AsyncClient, external_probe: Probe, user_token: str
) -> None:
    resp = await client.post(
        f"/api/v1/probes/{external_probe.id}/rotate-key",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_rotate_key_requires_auth(client: AsyncClient, external_probe: Probe) -> None:
    resp = await client.post(f"/api/v1/probes/{external_probe.id}/rotate-key")
    assert resp.status_code == 401, resp.text


@pytest.mark.asyncio
async def test_rotate_key_unknown_probe_404(client: AsyncClient, admin_token: str) -> None:
    import uuid

    resp = await client.post(
        f"/api/v1/probes/{uuid.uuid4()}/rotate-key",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_rotate_key_writes_audit_row(
    client: AsyncClient,
    external_probe: Probe,
    admin_user: User,
    admin_token: str,
    db_session: AsyncSession,
) -> None:
    """A successful rotation records a ``probe.rotate_key`` audit entry."""
    resp = await client.post(
        f"/api/v1/probes/{external_probe.id}/rotate-key",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200, resp.text

    entry = (
        await db_session.execute(
            select(AuditLog).where(
                AuditLog.action == "probe.rotate_key",
                AuditLog.object_id == external_probe.id,
            )
        )
    ).scalar_one()
    assert entry.object_type == "probe"
    assert entry.object_name == external_probe.name
    assert entry.user_id == admin_user.id
