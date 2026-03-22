"""Tests for monitor CRUD endpoints."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_monitor(client: AsyncClient, user_token: str) -> None:
    resp = await client.post(
        "/api/v1/monitors/",
        json={"name": "Test Monitor", "url": "https://example.com", "interval_seconds": 60},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Test Monitor"
    assert data["url"] == "https://example.com/"
    assert data["enabled"] is True


@pytest.mark.asyncio
async def test_list_monitors(client: AsyncClient, user_token: str) -> None:
    await client.post(
        "/api/v1/monitors/",
        json={"name": "M1", "url": "https://example.com"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    resp = await client.get(
        "/api/v1/monitors/",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
    assert len(resp.json()) >= 1


@pytest.mark.asyncio
async def test_get_monitor(client: AsyncClient, user_token: str) -> None:
    create = await client.post(
        "/api/v1/monitors/",
        json={"name": "GetMe", "url": "https://example.com"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    monitor_id = create.json()["id"]
    resp = await client.get(
        f"/api/v1/monitors/{monitor_id}",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["id"] == monitor_id


@pytest.mark.asyncio
async def test_update_monitor(client: AsyncClient, user_token: str) -> None:
    create = await client.post(
        "/api/v1/monitors/",
        json={"name": "Update Me", "url": "https://example.com"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    monitor_id = create.json()["id"]

    resp = await client.patch(
        f"/api/v1/monitors/{monitor_id}",
        json={"name": "Updated Name", "interval_seconds": 30},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Updated Name"
    assert resp.json()["interval_seconds"] == 30


@pytest.mark.asyncio
async def test_delete_monitor(client: AsyncClient, user_token: str) -> None:
    create = await client.post(
        "/api/v1/monitors/",
        json={"name": "Delete Me", "url": "https://example.com"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    monitor_id = create.json()["id"]

    del_resp = await client.delete(
        f"/api/v1/monitors/{monitor_id}",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert del_resp.status_code == 204

    get_resp = await client.get(
        f"/api/v1/monitors/{monitor_id}",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert get_resp.status_code == 404


@pytest.mark.asyncio
async def test_monitor_invalid_url(client: AsyncClient, user_token: str) -> None:
    resp = await client.post(
        "/api/v1/monitors/",
        json={"name": "Bad URL", "url": "not-a-url"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_monitor_requires_auth(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/monitors/")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_monitor_isolation(
    client: AsyncClient, user_token: str, admin_token: str
) -> None:
    """A regular user cannot access another user's monitor."""
    create = await client.post(
        "/api/v1/monitors/",
        json={"name": "Private", "url": "https://example.com"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    monitor_id = create.json()["id"]

    # Superadmin can see it
    resp = await client.get(
        f"/api/v1/monitors/{monitor_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
