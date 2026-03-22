"""Tests for monitor group endpoints."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_create_group(client: AsyncClient, user_token: str) -> None:
    resp = await client.post(
        "/api/v1/groups/",
        json={"name": "My Group"},
        headers=_auth(user_token),
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "My Group"


@pytest.mark.asyncio
async def test_list_groups(client: AsyncClient, user_token: str) -> None:
    await client.post(
        "/api/v1/groups/", json={"name": "G1"}, headers=_auth(user_token)
    )
    resp = await client.get("/api/v1/groups/", headers=_auth(user_token))
    assert resp.status_code == 200
    assert len(resp.json()) >= 1


@pytest.mark.asyncio
async def test_update_group(client: AsyncClient, user_token: str) -> None:
    create = await client.post(
        "/api/v1/groups/", json={"name": "ToUpdate"}, headers=_auth(user_token)
    )
    group_id = create.json()["id"]

    resp = await client.patch(
        f"/api/v1/groups/{group_id}",
        json={"name": "Updated Group"},
        headers=_auth(user_token),
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Updated Group"


@pytest.mark.asyncio
async def test_delete_group(client: AsyncClient, user_token: str) -> None:
    create = await client.post(
        "/api/v1/groups/", json={"name": "ToDelete"}, headers=_auth(user_token)
    )
    group_id = create.json()["id"]

    del_resp = await client.delete(
        f"/api/v1/groups/{group_id}", headers=_auth(user_token)
    )
    assert del_resp.status_code == 204


@pytest.mark.asyncio
async def test_group_slug_conflict(client: AsyncClient, user_token: str) -> None:
    await client.post(
        "/api/v1/groups/",
        json={"name": "SlugGroup1", "public_slug": "my-slug"},
        headers=_auth(user_token),
    )
    resp = await client.post(
        "/api/v1/groups/",
        json={"name": "SlugGroup2", "public_slug": "my-slug"},
        headers=_auth(user_token),
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_group_access_denied_for_other_user(
    client: AsyncClient, user_token: str, admin_token: str
) -> None:
    """Regular user cannot modify another user's group."""
    create = await client.post(
        "/api/v1/groups/", json={"name": "AdminGroup"}, headers=_auth(admin_token)
    )
    group_id = create.json()["id"]

    resp = await client.patch(
        f"/api/v1/groups/{group_id}",
        json={"name": "Hijacked"},
        headers=_auth(user_token),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_groups_require_auth(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/groups/")
    assert resp.status_code == 401
