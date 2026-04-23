"""Tests for authentication endpoints."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.conftest import TEST_PASSWORD
from whatisup.models.user import User


@pytest.mark.asyncio
async def test_register_disabled(client: AsyncClient) -> None:
    """Public registration is disabled — endpoint always returns 403."""
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": "test@example.com", "username": "testuser", "password": "SecurePass1"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_login_success(client: AsyncClient, admin_user: User) -> None:
    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": admin_user.email, "password": TEST_PASSWORD},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_login_wrong_password(client: AsyncClient, admin_user: User) -> None:
    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": admin_user.email, "password": "WrongPassword9"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_unknown_email(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": "nobody@example.com", "password": "AnyPass1"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_me(client: AsyncClient, admin_user: User, admin_token: str) -> None:
    resp = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == admin_user.email
    assert data["is_superadmin"] is True


@pytest.mark.asyncio
async def test_me_requires_auth(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 401


# ─────────────────────────────────────────────────────────────────────────────
# PATCH /auth/me — self-update (T1-13 timezone + full_name)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_me_update_timezone(client: AsyncClient, admin_token: str) -> None:
    resp = await client.patch(
        "/api/v1/auth/me",
        json={"timezone": "Europe/Paris"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["timezone"] == "Europe/Paris"

    # Persisted — GET /me returns the new value.
    fetched = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert fetched.json()["timezone"] == "Europe/Paris"


@pytest.mark.asyncio
async def test_me_update_timezone_invalid_rejected(client: AsyncClient, admin_token: str) -> None:
    resp = await client.patch(
        "/api/v1/auth/me",
        json={"timezone": "Not/A/Real/Zone"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_me_update_timezone_null_clears(client: AsyncClient, admin_token: str) -> None:
    """Sending an explicit null resets the user preference to browser-default."""
    await client.patch(
        "/api/v1/auth/me",
        json={"timezone": "Asia/Tokyo"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    resp = await client.patch(
        "/api/v1/auth/me",
        json={"timezone": None},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["timezone"] is None


@pytest.mark.asyncio
async def test_me_update_full_name(client: AsyncClient, admin_token: str) -> None:
    resp = await client.patch(
        "/api/v1/auth/me",
        json={"full_name": "Admin User"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["full_name"] == "Admin User"


@pytest.mark.asyncio
async def test_me_update_ignores_privileged_fields(client: AsyncClient, admin_token: str) -> None:
    """Users cannot escalate themselves via /auth/me — only whitelisted fields are accepted."""
    resp = await client.patch(
        "/api/v1/auth/me",
        json={"is_superadmin": False, "can_create_monitors": False},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    # `UserSelfUpdate` doesn't declare these fields — Pydantic ignores them
    # by default (extra='ignore') and the user stays superadmin.
    assert resp.status_code == 200
    assert resp.json()["is_superadmin"] is True


@pytest.mark.asyncio
async def test_me_update_requires_auth(client: AsyncClient) -> None:
    resp = await client.patch("/api/v1/auth/me", json={"timezone": "UTC"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_refresh_token(client: AsyncClient, admin_user: User) -> None:
    login = await client.post(
        "/api/v1/auth/login",
        data={"username": admin_user.email, "password": TEST_PASSWORD},
    )
    refresh = login.json()["refresh_token"]

    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert resp.status_code == 200
    assert "access_token" in resp.json()


@pytest.mark.asyncio
async def test_refresh_token_invalid(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": "not.a.valid.token"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_logout(client: AsyncClient, admin_user: User) -> None:
    login = await client.post(
        "/api/v1/auth/login",
        data={"username": admin_user.email, "password": TEST_PASSWORD},
    )
    refresh = login.json()["refresh_token"]

    resp = await client.post("/api/v1/auth/logout", json={"refresh_token": refresh})
    assert resp.status_code == 204

    # Refresh token should be revoked
    resp2 = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert resp2.status_code == 401


@pytest.mark.asyncio
async def test_oidc_config_disabled_by_default(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/auth/oidc/config")
    assert resp.status_code == 200
    assert resp.json()["enabled"] is False


@pytest.mark.asyncio
async def test_health_endpoint(client: AsyncClient) -> None:
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] in ("ok", "degraded")
