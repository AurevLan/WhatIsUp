"""Tests for admin endpoints (users, monitors, probe groups, OIDC settings)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.models.probe import Probe
from whatisup.models.user import User

# ── Helpers ───────────────────────────────────────────────────────────────────


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ── Users ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_admin_list_users(
    client: AsyncClient, admin_token: str, admin_user: User
) -> None:
    resp = await client.get("/api/v1/admin/users", headers=_auth(admin_token))
    assert resp.status_code == 200
    emails = [u["email"] for u in resp.json()]
    assert admin_user.email in emails


@pytest.mark.asyncio
async def test_admin_create_user(client: AsyncClient, admin_token: str) -> None:
    resp = await client.post(
        "/api/v1/admin/users",
        json={
            "email": "new@example.com",
            "password": "NewPass1!",
            "can_create_monitors": True,
        },
        headers=_auth(admin_token),
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["email"] == "new@example.com"
    assert data["is_superadmin"] is False


@pytest.mark.asyncio
async def test_admin_create_user_duplicate_email(
    client: AsyncClient, admin_token: str
) -> None:
    await client.post(
        "/api/v1/admin/users",
        json={"email": "dup@example.com", "password": "DupPass1!"},
        headers=_auth(admin_token),
    )
    resp = await client.post(
        "/api/v1/admin/users",
        json={"email": "dup@example.com", "password": "DupPass1!"},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_admin_update_user(
    client: AsyncClient, admin_token: str, regular_user: User
) -> None:
    resp = await client.patch(
        f"/api/v1/admin/users/{regular_user.id}",
        json={"is_active": False},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False


@pytest.mark.asyncio
async def test_admin_update_can_create_monitors(
    client: AsyncClient, admin_token: str, regular_user: User
) -> None:
    resp = await client.patch(
        f"/api/v1/admin/users/{regular_user.id}",
        json={"can_create_monitors": False},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 200
    assert resp.json()["can_create_monitors"] is False


@pytest.mark.asyncio
async def test_admin_delete_user(
    client: AsyncClient, admin_token: str
) -> None:
    create = await client.post(
        "/api/v1/admin/users",
        json={"email": "todelete@example.com", "password": "DelPass1!"},
        headers=_auth(admin_token),
    )
    user_id = create.json()["id"]
    resp = await client.delete(
        f"/api/v1/admin/users/{user_id}", headers=_auth(admin_token)
    )
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_admin_cannot_delete_self(
    client: AsyncClient, admin_token: str, admin_user: User
) -> None:
    resp = await client.delete(
        f"/api/v1/admin/users/{admin_user.id}", headers=_auth(admin_token)
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_admin_requires_superadmin(
    client: AsyncClient, user_token: str
) -> None:
    resp = await client.get("/api/v1/admin/users", headers=_auth(user_token))
    assert resp.status_code == 403


# ── All monitors ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_admin_list_all_monitors(
    client: AsyncClient, admin_token: str, user_token: str
) -> None:
    await client.post(
        "/api/v1/monitors/",
        json={"name": "AdminMon", "url": "https://example.com"},
        headers=_auth(user_token),
    )
    resp = await client.get("/api/v1/admin/monitors", headers=_auth(admin_token))
    assert resp.status_code == 200
    names = [m["name"] for m in resp.json()]
    assert "AdminMon" in names


# ── Probe groups ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_admin_probe_groups_crud(
    client: AsyncClient, admin_token: str
) -> None:
    # Create
    resp = await client.post(
        "/api/v1/admin/probe-groups",
        json={"name": "Group A", "description": "Test group"},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 201
    group_id = resp.json()["id"]

    # List
    list_resp = await client.get(
        "/api/v1/admin/probe-groups", headers=_auth(admin_token)
    )
    assert list_resp.status_code == 200
    assert any(g["id"] == group_id for g in list_resp.json())

    # Update
    patch_resp = await client.patch(
        f"/api/v1/admin/probe-groups/{group_id}",
        json={"name": "Group A Updated"},
        headers=_auth(admin_token),
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["name"] == "Group A Updated"

    # Delete
    del_resp = await client.delete(
        f"/api/v1/admin/probe-groups/{group_id}", headers=_auth(admin_token)
    )
    assert del_resp.status_code == 204


@pytest.mark.asyncio
async def test_admin_probe_group_add_remove_probe(
    client: AsyncClient, admin_token: str, db_session: AsyncSession
) -> None:
    probe = Probe(name="p1", location_name="Paris", api_key_hash="x")
    db_session.add(probe)
    await db_session.flush()

    create = await client.post(
        "/api/v1/admin/probe-groups",
        json={"name": "WithProbe"},
        headers=_auth(admin_token),
    )
    group_id = create.json()["id"]

    add_resp = await client.post(
        f"/api/v1/admin/probe-groups/{group_id}/probes",
        json={"probe_ids": [str(probe.id)]},
        headers=_auth(admin_token),
    )
    assert add_resp.status_code == 200
    assert str(probe.id) in add_resp.json()["probe_ids"]

    rm_resp = await client.delete(
        f"/api/v1/admin/probe-groups/{group_id}/probes/{probe.id}",
        headers=_auth(admin_token),
    )
    assert rm_resp.status_code == 204


@pytest.mark.asyncio
async def test_admin_probe_group_add_remove_user(
    client: AsyncClient, admin_token: str, regular_user: User
) -> None:
    create = await client.post(
        "/api/v1/admin/probe-groups",
        json={"name": "WithUser"},
        headers=_auth(admin_token),
    )
    group_id = create.json()["id"]

    grant_resp = await client.post(
        f"/api/v1/admin/probe-groups/{group_id}/users",
        json={"user_ids": [str(regular_user.id)]},
        headers=_auth(admin_token),
    )
    assert grant_resp.status_code == 200
    assert str(regular_user.id) in grant_resp.json()["user_ids"]

    revoke_resp = await client.delete(
        f"/api/v1/admin/probe-groups/{group_id}/users/{regular_user.id}",
        headers=_auth(admin_token),
    )
    assert revoke_resp.status_code == 204


# ── OIDC settings ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_admin_get_oidc_settings_env_fallback(
    client: AsyncClient, admin_token: str
) -> None:
    """No DB row yet → source should be 'env'."""
    resp = await client.get("/api/v1/admin/settings/oidc", headers=_auth(admin_token))
    assert resp.status_code == 200
    data = resp.json()
    assert data["source"] == "env"
    assert data["oidc_enabled"] is False
    assert "oidc_client_secret_set" in data


@pytest.mark.asyncio
async def test_admin_update_oidc_settings(
    client: AsyncClient, admin_token: str
) -> None:
    payload = {
        "oidc_enabled": True,
        "oidc_issuer_url": "https://accounts.example.com",
        "oidc_client_id": "my-client",
        "oidc_client_secret": "super-secret",
        "oidc_redirect_uri": "",
        "oidc_scopes": "openid email profile",
        "oidc_auto_provision": False,
    }
    resp = await client.put(
        "/api/v1/admin/settings/oidc", json=payload, headers=_auth(admin_token)
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["source"] == "db"
    assert data["oidc_enabled"] is True
    assert data["oidc_issuer_url"] == "https://accounts.example.com"
    assert data["oidc_client_id"] == "my-client"
    # Secret must never be returned
    assert "oidc_client_secret" not in data
    assert data["oidc_client_secret_set"] is True
    assert data["oidc_auto_provision"] is False


@pytest.mark.asyncio
async def test_admin_oidc_secret_kept_when_not_provided(
    client: AsyncClient, admin_token: str
) -> None:
    """Sending oidc_client_secret=null should preserve the existing secret."""
    await client.put(
        "/api/v1/admin/settings/oidc",
        json={
            "oidc_enabled": True,
            "oidc_issuer_url": "https://issuer.example.com",
            "oidc_client_id": "cid",
            "oidc_client_secret": "initial-secret",
            "oidc_scopes": "openid email",
            "oidc_auto_provision": True,
        },
        headers=_auth(admin_token),
    )
    # Now update without providing the secret
    resp = await client.put(
        "/api/v1/admin/settings/oidc",
        json={
            "oidc_enabled": False,
            "oidc_issuer_url": "https://issuer.example.com",
            "oidc_client_id": "cid",
            "oidc_client_secret": None,
            "oidc_scopes": "openid email",
            "oidc_auto_provision": True,
        },
        headers=_auth(admin_token),
    )
    assert resp.status_code == 200
    assert resp.json()["oidc_client_secret_set"] is True


@pytest.mark.asyncio
async def test_admin_oidc_get_reflects_db_after_update(
    client: AsyncClient, admin_token: str
) -> None:
    await client.put(
        "/api/v1/admin/settings/oidc",
        json={
            "oidc_enabled": True,
            "oidc_issuer_url": "https://sso.example.com",
            "oidc_client_id": "client-x",
            "oidc_client_secret": "s3cr3t",
            "oidc_scopes": "openid",
            "oidc_auto_provision": True,
        },
        headers=_auth(admin_token),
    )
    get_resp = await client.get(
        "/api/v1/admin/settings/oidc", headers=_auth(admin_token)
    )
    assert get_resp.status_code == 200
    data = get_resp.json()
    assert data["source"] == "db"
    assert data["oidc_issuer_url"] == "https://sso.example.com"


@pytest.mark.asyncio
async def test_admin_oidc_requires_superadmin(
    client: AsyncClient, user_token: str
) -> None:
    resp = await client.get(
        "/api/v1/admin/settings/oidc", headers=_auth(user_token)
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_oidc_config_reflects_db_enabled(
    client: AsyncClient, admin_token: str
) -> None:
    """After enabling OIDC in DB, /auth/oidc/config should return enabled=True."""
    await client.put(
        "/api/v1/admin/settings/oidc",
        json={
            "oidc_enabled": True,
            "oidc_issuer_url": "https://issuer.example.com",
            "oidc_client_id": "cid",
            "oidc_client_secret": "s",
            "oidc_scopes": "openid",
            "oidc_auto_provision": True,
        },
        headers=_auth(admin_token),
    )
    resp = await client.get("/api/v1/auth/oidc/config")
    assert resp.status_code == 200
    assert resp.json()["enabled"] is True
