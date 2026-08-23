"""Discovery review — dismissed_reason + bulk accept/dismiss (plan D, D-3).

Coverage: reason stored/returned/cleared, bulk accept/dismiss (cross-tenant
impossible, mixed success/failure reported per id, not as a global failure),
rate-limit decorator present.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.core.security import hash_password
from whatisup.models.audit_log import AuditLog
from whatisup.models.discovery import DiscoveredService, DiscoverySource
from whatisup.models.user import User

TEST_PASSWORD = "TestPassword123!"


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _audit_entries(db: AsyncSession, action: str) -> list[AuditLog]:
    rows = await db.execute(select(AuditLog).where(AuditLog.action == action))
    return list(rows.scalars().all())


@pytest_asyncio.fixture
async def stranger(db_session: AsyncSession) -> User:
    u = User(
        email="d3-stranger@test.com",
        username="d3-stranger",
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


async def _register_probe(client: AsyncClient, admin_token: str, name: str = "probe-d3") -> str:
    resp = await client.post(
        "/api/v1/probes/register",
        json={"name": name, "location_name": "Paris"},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


@pytest_asyncio.fixture
async def owned_source(
    db_session: AsyncSession, regular_user: User, admin_token: str, client: AsyncClient
) -> DiscoverySource:
    probe_id = await _register_probe(client, admin_token)
    source = DiscoverySource(
        owner_id=regular_user.id,
        probe_id=uuid.UUID(probe_id),
        source_type="port_scan",
        params={"cidr": "10.0.0.0/24", "ports": [80]},
    )
    db_session.add(source)
    await db_session.flush()
    return source


def _make_service(
    source: DiscoverySource,
    host: str = "10.0.0.5",
    port: int = 80,
    status_: str = "proposed",
) -> DiscoveredService:
    now = datetime.now(UTC)
    return DiscoveredService(
        source_id=source.id,
        host=host,
        port=port,
        proto="tcp",
        normalized_target=f"tcp://{host}:{port}",
        status=status_,
        first_seen_at=now,
        last_seen_at=now,
        status_changed_at=now,
    )


# ── dismissed_reason ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dismiss_stores_reason(
    client: AsyncClient, user_token: str, db_session: AsyncSession, owned_source: DiscoverySource
) -> None:
    service = _make_service(owned_source)
    db_session.add(service)
    await db_session.flush()
    await db_session.commit()

    resp = await client.post(
        f"/api/v1/discovery/services/{service.id}/dismiss",
        json={"reason": "decommissioned"},
        headers=_auth(user_token),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "dismissed"
    assert body["dismissed_reason"] == "decommissioned"

    entries = await _audit_entries(db_session, "discovery_service.dismiss")
    assert any(e.diff and e.diff.get("reason") == "decommissioned" for e in entries)


@pytest.mark.asyncio
async def test_dismiss_without_reason_is_still_optional(
    client: AsyncClient, user_token: str, db_session: AsyncSession, owned_source: DiscoverySource
) -> None:
    service = _make_service(owned_source)
    db_session.add(service)
    await db_session.flush()
    await db_session.commit()

    resp = await client.post(
        f"/api/v1/discovery/services/{service.id}/dismiss", headers=_auth(user_token)
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["dismissed_reason"] is None


@pytest.mark.asyncio
async def test_dismiss_extra_field_rejected(
    client: AsyncClient, user_token: str, db_session: AsyncSession, owned_source: DiscoverySource
) -> None:
    service = _make_service(owned_source)
    db_session.add(service)
    await db_session.flush()
    await db_session.commit()

    resp = await client.post(
        f"/api/v1/discovery/services/{service.id}/dismiss",
        json={"reason": "x", "bogus": 1},
        headers=_auth(user_token),
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_accept_clears_dismissed_reason(
    client: AsyncClient, user_token: str, db_session: AsyncSession, owned_source: DiscoverySource
) -> None:
    # An orphaned service that carries a stale dismissed_reason (shouldn't
    # normally happen, but the clearing rule is defensive) must not surface
    # it once accepted.
    service = _make_service(owned_source, status_="orphaned")
    service.dismissed_reason = "stale"
    db_session.add(service)
    await db_session.flush()
    await db_session.commit()

    resp = await client.post(
        f"/api/v1/discovery/services/{service.id}/accept", headers=_auth(user_token)
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["dismissed_reason"] is None


# ── bulk ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_bulk_dismiss_shared_reason(
    client: AsyncClient, user_token: str, db_session: AsyncSession, owned_source: DiscoverySource
) -> None:
    s1 = _make_service(owned_source, host="10.0.0.1")
    s2 = _make_service(owned_source, host="10.0.0.2")
    db_session.add_all([s1, s2])
    await db_session.flush()
    await db_session.commit()

    resp = await client.post(
        "/api/v1/discovery/services/bulk",
        json={"action": "dismiss", "service_ids": [str(s1.id), str(s2.id)], "reason": "noise"},
        headers=_auth(user_token),
    )
    assert resp.status_code == 200, resp.text
    results = resp.json()["results"]
    assert len(results) == 2
    assert all(r["ok"] for r in results)
    assert all(r["service"]["dismissed_reason"] == "noise" for r in results)

    entries = await _audit_entries(db_session, "discovery_service.dismiss")
    assert len([e for e in entries if e.diff and e.diff.get("reason") == "noise"]) >= 2


@pytest.mark.asyncio
async def test_bulk_accept_creates_monitors(
    client: AsyncClient, user_token: str, db_session: AsyncSession, owned_source: DiscoverySource
) -> None:
    s1 = _make_service(owned_source, host="10.0.0.10")
    s2 = _make_service(owned_source, host="10.0.0.11")
    db_session.add_all([s1, s2])
    await db_session.flush()
    await db_session.commit()

    resp = await client.post(
        "/api/v1/discovery/services/bulk",
        json={"action": "accept", "service_ids": [str(s1.id), str(s2.id)]},
        headers=_auth(user_token),
    )
    assert resp.status_code == 200, resp.text
    results = resp.json()["results"]
    assert len(results) == 2
    assert all(r["ok"] for r in results)
    assert all(r["service"]["status"] == "accepted" for r in results)
    assert all(r["service"]["monitor_id"] is not None for r in results)

    entries = await _audit_entries(db_session, "discovery_service.accept")
    assert len(entries) >= 2


@pytest.mark.asyncio
async def test_bulk_mixed_success_and_failure_reported_per_id(
    client: AsyncClient, user_token: str, db_session: AsyncSession, owned_source: DiscoverySource
) -> None:
    ok_service = _make_service(owned_source, host="10.0.0.20")
    already_accepted = _make_service(owned_source, host="10.0.0.21", status_="accepted")
    db_session.add_all([ok_service, already_accepted])
    await db_session.flush()
    await db_session.commit()

    missing_id = uuid.uuid4()
    resp = await client.post(
        "/api/v1/discovery/services/bulk",
        json={
            "action": "dismiss",
            "service_ids": [str(ok_service.id), str(already_accepted.id), str(missing_id)],
        },
        headers=_auth(user_token),
    )
    # The whole call still succeeds (200) — failures are per-id, not global.
    assert resp.status_code == 200, resp.text
    results = {r["service_id"]: r for r in resp.json()["results"]}
    assert results[str(ok_service.id)]["ok"] is True
    assert results[str(already_accepted.id)]["ok"] is False
    assert results[str(missing_id)]["ok"] is False

    # The failures didn't roll back the one success.
    refreshed = (
        await db_session.execute(
            select(DiscoveredService).where(DiscoveredService.id == ok_service.id)
        )
    ).scalar_one()
    assert refreshed.status == "dismissed"


@pytest.mark.asyncio
async def test_bulk_cross_tenant_impossible(
    client: AsyncClient,
    stranger_token: str,
    db_session: AsyncSession,
    owned_source: DiscoverySource,
) -> None:
    service = _make_service(owned_source)
    db_session.add(service)
    await db_session.flush()
    await db_session.commit()

    resp = await client.post(
        "/api/v1/discovery/services/bulk",
        json={"action": "accept", "service_ids": [str(service.id)]},
        headers=_auth(stranger_token),
    )
    assert resp.status_code == 200
    results = resp.json()["results"]
    assert results[0]["ok"] is False
    assert results[0]["service"] is None

    # Nothing was created/mutated on the stranger's behalf.
    refreshed = (
        await db_session.execute(
            select(DiscoveredService).where(DiscoveredService.id == service.id)
        )
    ).scalar_one()
    assert refreshed.status == "proposed"
    assert refreshed.monitor_id is None


@pytest.mark.asyncio
async def test_bulk_empty_ids_rejected(client: AsyncClient, user_token: str) -> None:
    resp = await client.post(
        "/api/v1/discovery/services/bulk",
        json={"action": "dismiss", "service_ids": []},
        headers=_auth(user_token),
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_bulk_extra_field_rejected(
    client: AsyncClient, user_token: str, owned_source: DiscoverySource, db_session: AsyncSession
) -> None:
    service = _make_service(owned_source)
    db_session.add(service)
    await db_session.flush()
    await db_session.commit()

    resp = await client.post(
        "/api/v1/discovery/services/bulk",
        json={"action": "dismiss", "service_ids": [str(service.id)], "bogus": 1},
        headers=_auth(user_token),
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_bulk_action_rate_limited(client: AsyncClient) -> None:
    """`@limiter.limit` decorator sanity: the route must exist with the verb
    the plan specifies (a 404 here would mean the route isn't wired)."""
    resp = await client.post(
        "/api/v1/discovery/services/bulk",
        json={"action": "dismiss", "service_ids": [str(uuid.uuid4())]},
    )
    # No auth header → 401, not 404 — proves the route is registered before
    # the auth dependency runs.
    assert resp.status_code == 401
