"""Admin / Teams / Alert advanced endpoint tests — coverage boost."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Admin — users
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_create_user(client: AsyncClient, admin_token: str) -> None:
    resp = await client.post(
        "/api/v1/admin/users",
        json={
            "email": "newuser@example.com",
            "password": "VeryStrongPass1!",
            "is_superadmin": False,
            "can_create_monitors": True,
        },
        headers=_auth(admin_token),
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["email"] == "newuser@example.com"
    assert "username" in data


@pytest.mark.asyncio
async def test_admin_create_user_duplicate_409(client: AsyncClient, admin_token: str) -> None:
    payload = {
        "email": "dup@example.com",
        "password": "VeryStrongPass1!",
    }
    r1 = await client.post("/api/v1/admin/users", json=payload, headers=_auth(admin_token))
    assert r1.status_code == 201
    r2 = await client.post("/api/v1/admin/users", json=payload, headers=_auth(admin_token))
    assert r2.status_code == 409


@pytest.mark.asyncio
async def test_admin_list_users(client: AsyncClient, admin_token: str) -> None:
    resp = await client.get("/api/v1/admin/users", headers=_auth(admin_token))
    assert resp.status_code == 200
    items = resp.json()
    assert isinstance(items, list)
    assert any(u["email"] == "admin@test.com" for u in items)
    for u in items:
        assert "monitor_count" in u


@pytest.mark.asyncio
async def test_admin_update_user(client: AsyncClient, admin_token: str) -> None:
    create = await client.post(
        "/api/v1/admin/users",
        json={
            "email": "upduser@example.com",
            "password": "VeryStrongPass1!",
        },
        headers=_auth(admin_token),
    )
    user_id = create.json()["id"]

    upd = await client.patch(
        f"/api/v1/admin/users/{user_id}",
        json={"full_name": "Updated Name", "is_active": False},
        headers=_auth(admin_token),
    )
    assert upd.status_code == 200
    assert upd.json()["full_name"] == "Updated Name"


@pytest.mark.asyncio
async def test_admin_update_user_unknown_404(client: AsyncClient, admin_token: str) -> None:
    resp = await client.patch(
        f"/api/v1/admin/users/{uuid.uuid4()}",
        json={"full_name": "X"},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_admin_delete_user(client: AsyncClient, admin_token: str) -> None:
    create = await client.post(
        "/api/v1/admin/users",
        json={
            "email": "deluser@example.com",
            "password": "VeryStrongPass1!",
        },
        headers=_auth(admin_token),
    )
    user_id = create.json()["id"]
    resp = await client.delete(f"/api/v1/admin/users/{user_id}", headers=_auth(admin_token))
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_admin_delete_self_400(client: AsyncClient, admin_token: str, admin_user) -> None:
    resp = await client.delete(f"/api/v1/admin/users/{admin_user.id}", headers=_auth(admin_token))
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_admin_demote_self_400(client: AsyncClient, admin_token: str, admin_user) -> None:
    resp = await client.patch(
        f"/api/v1/admin/users/{admin_user.id}",
        json={"is_superadmin": False},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_admin_requires_superadmin(client: AsyncClient, user_token: str) -> None:
    resp = await client.get("/api/v1/admin/users", headers=_auth(user_token))
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Admin — monitors / probe groups / oidc
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_list_all_monitors(client: AsyncClient, admin_token: str) -> None:
    await client.post(
        "/api/v1/monitors/",
        json={"name": "GlobalView", "url": "https://example.com"},
        headers=_auth(admin_token),
    )
    resp = await client.get("/api/v1/admin/monitors", headers=_auth(admin_token))
    assert resp.status_code == 200
    items = resp.json()
    assert any(m["name"] == "GlobalView" for m in items)


@pytest.mark.asyncio
async def test_admin_probe_groups_crud(client: AsyncClient, admin_token: str) -> None:
    # Create
    create = await client.post(
        "/api/v1/admin/probe-groups",
        json={"name": "EU", "description": "European probes"},
        headers=_auth(admin_token),
    )
    assert create.status_code == 201
    grp = create.json()
    assert grp["name"] == "EU"
    group_id = grp["id"]

    # Duplicate name → 409
    dup = await client.post(
        "/api/v1/admin/probe-groups",
        json={"name": "EU"},
        headers=_auth(admin_token),
    )
    assert dup.status_code == 409

    # List
    lst = await client.get("/api/v1/admin/probe-groups", headers=_auth(admin_token))
    assert lst.status_code == 200
    assert any(g["id"] == group_id for g in lst.json())

    # Update
    upd = await client.patch(
        f"/api/v1/admin/probe-groups/{group_id}",
        json={"name": "EU-renamed", "description": "New desc"},
        headers=_auth(admin_token),
    )
    assert upd.status_code == 200
    assert upd.json()["name"] == "EU-renamed"

    # Delete
    delete_resp = await client.delete(
        f"/api/v1/admin/probe-groups/{group_id}", headers=_auth(admin_token)
    )
    assert delete_resp.status_code == 204


@pytest.mark.asyncio
async def test_admin_probe_group_404(client: AsyncClient, admin_token: str) -> None:
    resp = await client.patch(
        f"/api/v1/admin/probe-groups/{uuid.uuid4()}",
        json={"name": "X"},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_admin_oidc_settings_default_env(client: AsyncClient, admin_token: str) -> None:
    resp = await client.get("/api/v1/admin/settings/oidc", headers=_auth(admin_token))
    assert resp.status_code == 200
    data = resp.json()
    assert data["source"] in ("db", "env")
    assert "oidc_enabled" in data


@pytest.mark.asyncio
async def test_admin_oidc_settings_update(client: AsyncClient, admin_token: str) -> None:
    resp = await client.put(
        "/api/v1/admin/settings/oidc",
        json={
            "oidc_enabled": True,
            "oidc_issuer_url": "https://example.com/oidc",
            "oidc_client_id": "client123",
            "oidc_client_secret": "secret123",
            "oidc_redirect_uri": "https://example.com/callback",
            "oidc_scopes": "openid email",
            "oidc_auto_provision": False,
        },
        headers=_auth(admin_token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["source"] == "db"
    assert data["oidc_enabled"] is True
    assert data["oidc_client_secret_set"] is True

    # Now clear the secret with empty string
    clear = await client.put(
        "/api/v1/admin/settings/oidc",
        json={
            "oidc_enabled": False,
            "oidc_issuer_url": "",
            "oidc_client_id": "",
            "oidc_client_secret": "",
            "oidc_redirect_uri": "",
            "oidc_scopes": "",
            "oidc_auto_provision": True,
        },
        headers=_auth(admin_token),
    )
    assert clear.status_code == 200
    assert clear.json()["oidc_client_secret_set"] is False


# ---------------------------------------------------------------------------
# Teams CRUD + members
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_teams_create_and_get(client: AsyncClient, user_token: str) -> None:
    resp = await client.post("/api/v1/teams/", json={"name": "MyTeam"}, headers=_auth(user_token))
    assert resp.status_code == 201
    team = resp.json()
    assert team["name"] == "MyTeam"
    assert team["slug"] == "myteam"

    get_resp = await client.get(f"/api/v1/teams/{team['id']}", headers=_auth(user_token))
    assert get_resp.status_code == 200
    assert get_resp.json()["member_count"] == 1


@pytest.mark.asyncio
async def test_teams_create_duplicate_slug_409(client: AsyncClient, user_token: str) -> None:
    payload = {"name": "Same", "slug": "same-team"}
    r1 = await client.post("/api/v1/teams/", json=payload, headers=_auth(user_token))
    assert r1.status_code == 201
    r2 = await client.post("/api/v1/teams/", json=payload, headers=_auth(user_token))
    assert r2.status_code == 409


@pytest.mark.asyncio
async def test_teams_list(client: AsyncClient, user_token: str) -> None:
    await client.post("/api/v1/teams/", json={"name": "TL1"}, headers=_auth(user_token))
    await client.post("/api/v1/teams/", json={"name": "TL2"}, headers=_auth(user_token))
    resp = await client.get("/api/v1/teams/", headers=_auth(user_token))
    assert resp.status_code == 200
    assert len(resp.json()) >= 2


@pytest.mark.asyncio
async def test_teams_update(client: AsyncClient, user_token: str) -> None:
    create = await client.post("/api/v1/teams/", json={"name": "TU1"}, headers=_auth(user_token))
    team_id = create.json()["id"]
    upd = await client.patch(
        f"/api/v1/teams/{team_id}",
        json={"name": "TU1-renamed"},
        headers=_auth(user_token),
    )
    assert upd.status_code == 200
    assert upd.json()["name"] == "TU1-renamed"


@pytest.mark.asyncio
async def test_teams_delete(client: AsyncClient, user_token: str) -> None:
    create = await client.post("/api/v1/teams/", json={"name": "TD1"}, headers=_auth(user_token))
    team_id = create.json()["id"]
    resp = await client.delete(f"/api/v1/teams/{team_id}", headers=_auth(user_token))
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_teams_get_404(client: AsyncClient, user_token: str) -> None:
    resp = await client.get(f"/api/v1/teams/{uuid.uuid4()}", headers=_auth(user_token))
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_team_members_list(client: AsyncClient, user_token: str) -> None:
    create = await client.post("/api/v1/teams/", json={"name": "TM1"}, headers=_auth(user_token))
    team_id = create.json()["id"]
    resp = await client.get(f"/api/v1/teams/{team_id}/members", headers=_auth(user_token))
    assert resp.status_code == 200
    members = resp.json()
    assert len(members) == 1  # creator is owner
    assert members[0]["role"] == "owner"


@pytest.mark.asyncio
async def test_team_add_member_and_update_role(client: AsyncClient, admin_token: str) -> None:
    """An admin creates a team, adds a second user, updates role, then removes."""
    # Create team as admin
    team_create = await client.post(
        "/api/v1/teams/", json={"name": "TAdd"}, headers=_auth(admin_token)
    )
    team_id = team_create.json()["id"]

    # Create a user via admin endpoint
    user_create = await client.post(
        "/api/v1/admin/users",
        json={"email": "teammate@example.com", "password": "VeryStrongPass1!"},
        headers=_auth(admin_token),
    )
    user_id = user_create.json()["id"]

    # Add as member
    add = await client.post(
        f"/api/v1/teams/{team_id}/members",
        json={"user_id": user_id, "role": "editor"},
        headers=_auth(admin_token),
    )
    assert add.status_code == 201
    assert add.json()["role"] == "editor"

    # Duplicate add → 409
    dup = await client.post(
        f"/api/v1/teams/{team_id}/members",
        json={"user_id": user_id, "role": "viewer"},
        headers=_auth(admin_token),
    )
    assert dup.status_code == 409

    # Add unknown user → 404
    not_found = await client.post(
        f"/api/v1/teams/{team_id}/members",
        json={"user_id": str(uuid.uuid4()), "role": "viewer"},
        headers=_auth(admin_token),
    )
    assert not_found.status_code == 404

    # Update role
    upd = await client.patch(
        f"/api/v1/teams/{team_id}/members/{user_id}",
        json={"role": "admin"},
        headers=_auth(admin_token),
    )
    assert upd.status_code == 200
    assert upd.json()["role"] == "admin"

    # Update unknown member → 404
    not_member = await client.patch(
        f"/api/v1/teams/{team_id}/members/{uuid.uuid4()}",
        json={"role": "viewer"},
        headers=_auth(admin_token),
    )
    assert not_member.status_code == 404

    # Remove member
    rm = await client.delete(
        f"/api/v1/teams/{team_id}/members/{user_id}",
        headers=_auth(admin_token),
    )
    assert rm.status_code == 204

    # Remove unknown member → 404
    rm_404 = await client.delete(
        f"/api/v1/teams/{team_id}/members/{uuid.uuid4()}",
        headers=_auth(admin_token),
    )
    assert rm_404.status_code == 404


@pytest.mark.asyncio
async def test_team_cannot_remove_last_owner(
    client: AsyncClient, user_token: str, regular_user
) -> None:
    create = await client.post(
        "/api/v1/teams/", json={"name": "LastOwner"}, headers=_auth(user_token)
    )
    team_id = create.json()["id"]
    # Try to remove self (the only owner)
    resp = await client.delete(
        f"/api/v1/teams/{team_id}/members/{regular_user.id}",
        headers=_auth(user_token),
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_team_non_member_403(client: AsyncClient, user_token: str, admin_token: str) -> None:
    # Admin creates a team; regular user is not a member
    create = await client.post(
        "/api/v1/teams/", json={"name": "AdminTeam"}, headers=_auth(admin_token)
    )
    team_id = create.json()["id"]
    resp = await client.get(f"/api/v1/teams/{team_id}", headers=_auth(user_token))
    assert resp.status_code == 403
