"""B3 — heartbeat slug per-owner + globally unique heartbeat_token."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.core.security import hash_password
from whatisup.models.user import User

TEST_PASSWORD = "TestPass1!"


async def _login(client: AsyncClient, email: str) -> str:
    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": email, "password": TEST_PASSWORD},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _hb_payload(slug: str) -> dict:
    return {
        "name": f"hb-{slug}",
        "url": "http://hb",
        "check_type": "heartbeat",
        "heartbeat_slug": slug,
        "heartbeat_interval_seconds": 3600,
        "heartbeat_grace_seconds": 60,
    }


@pytest.mark.asyncio
async def test_create_heartbeat_returns_token(client: AsyncClient, user_token: str) -> None:
    """Creating a heartbeat monitor surfaces a server-generated token."""
    resp = await client.post(
        "/api/v1/monitors/",
        json=_hb_payload("nightly-backup"),
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["heartbeat_slug"] == "nightly-backup"
    token = data["heartbeat_token"]
    assert token and isinstance(token, str)
    # token_urlsafe(32) → ~43 chars
    assert len(token) >= 40


@pytest.mark.asyncio
async def test_ping_routes_by_token_not_slug(client: AsyncClient, user_token: str) -> None:
    create = await client.post(
        "/api/v1/monitors/",
        json=_hb_payload("daily"),
        headers={"Authorization": f"Bearer {user_token}"},
    )
    token = create.json()["heartbeat_token"]

    # Slug-based path is no longer addressable
    miss = await client.post("/api/v1/ping/daily")
    assert miss.status_code == 404

    # Token-based path works (POST + GET)
    ok = await client.post(f"/api/v1/ping/{token}")
    assert ok.status_code == 200
    assert ok.json()["ok"] is True

    ok_get = await client.get(f"/api/v1/ping/{token}")
    assert ok_get.status_code == 200


@pytest.mark.asyncio
async def test_two_owners_can_share_slug(
    client: AsyncClient,
    user_token: str,
    db_session: AsyncSession,
) -> None:
    """Same slug across owners must coexist (composite UQ owner_id, slug)."""
    # Owner 1 creates "backup"
    r1 = await client.post(
        "/api/v1/monitors/",
        json=_hb_payload("backup"),
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert r1.status_code == 201

    # Owner 2: create a separate user + token, then post "backup" too
    other = User(
        email="other@test.com",
        username="other",
        hashed_password=hash_password(TEST_PASSWORD),
        is_superadmin=False,
        can_create_monitors=True,
    )
    db_session.add(other)
    await db_session.flush()

    other_token = await _login(client, other.email)
    r2 = await client.post(
        "/api/v1/monitors/",
        json=_hb_payload("backup"),
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert r2.status_code == 201, r2.text

    # Each owner pings their own monitor via distinct tokens
    t1, t2 = r1.json()["heartbeat_token"], r2.json()["heartbeat_token"]
    assert t1 != t2
    assert (await client.post(f"/api/v1/ping/{t1}")).status_code == 200
    assert (await client.post(f"/api/v1/ping/{t2}")).status_code == 200


@pytest.mark.asyncio
async def test_same_owner_cannot_reuse_slug(client: AsyncClient, user_token: str) -> None:
    """A single owner still gets a clean error when reusing a slug."""
    r1 = await client.post(
        "/api/v1/monitors/",
        json=_hb_payload("cron"),
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert r1.status_code == 201

    r2 = await client.post(
        "/api/v1/monitors/",
        json=_hb_payload("cron"),
        headers={"Authorization": f"Bearer {user_token}"},
    )
    # 4xx or 5xx — must not silently succeed and create a duplicate.
    assert r2.status_code >= 400, r2.text


@pytest.mark.asyncio
async def test_ping_with_unknown_token_returns_404(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/ping/this-token-does-not-exist")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_converting_to_heartbeat_backfills_token(
    client: AsyncClient, user_token: str
) -> None:
    """Patching an existing monitor to add a slug generates the token."""
    create = await client.post(
        "/api/v1/monitors/",
        json={"name": "http-mon", "url": "https://example.com"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert create.status_code == 201
    monitor_id = create.json()["id"]
    assert create.json()["heartbeat_token"] is None

    patch = await client.patch(
        f"/api/v1/monitors/{monitor_id}",
        json={"check_type": "heartbeat", "heartbeat_slug": "added-later"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert patch.status_code == 200, patch.text
    assert patch.json()["heartbeat_token"]
