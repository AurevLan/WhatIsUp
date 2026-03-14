"""Tests for monitor CRUD endpoints."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


async def _get_token(client: AsyncClient, suffix: str = "") -> str:
    email = f"monitor_test{suffix}@example.com"
    username = f"monitortest{suffix}"
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "username": username,
            "password": "SecurePass1",
        },
    )
    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": email, "password": "SecurePass1"},
    )
    return resp.json()["access_token"]


@pytest.mark.asyncio
async def test_create_monitor(client: AsyncClient) -> None:
    token = await _get_token(client, "create")
    resp = await client.post(
        "/api/v1/monitors/",
        json={
            "name": "Test Monitor",
            "url": "https://example.com",
            "interval_seconds": 60,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Test Monitor"
    assert data["url"] == "https://example.com/"
    assert data["enabled"] is True


@pytest.mark.asyncio
async def test_list_monitors(client: AsyncClient) -> None:
    token = await _get_token(client, "list")
    await client.post(
        "/api/v1/monitors/",
        json={"name": "M1", "url": "https://example.com"},
        headers={"Authorization": f"Bearer {token}"},
    )
    resp = await client.get(
        "/api/v1/monitors/",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
    assert len(resp.json()) >= 1


@pytest.mark.asyncio
async def test_update_monitor(client: AsyncClient) -> None:
    token = await _get_token(client, "update")
    create_resp = await client.post(
        "/api/v1/monitors/",
        json={"name": "Update Me", "url": "https://example.com"},
        headers={"Authorization": f"Bearer {token}"},
    )
    monitor_id = create_resp.json()["id"]

    resp = await client.patch(
        f"/api/v1/monitors/{monitor_id}",
        json={"name": "Updated Name", "interval_seconds": 30},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Updated Name"
    assert resp.json()["interval_seconds"] == 30


@pytest.mark.asyncio
async def test_delete_monitor(client: AsyncClient) -> None:
    token = await _get_token(client, "delete")
    create_resp = await client.post(
        "/api/v1/monitors/",
        json={"name": "Delete Me", "url": "https://example.com"},
        headers={"Authorization": f"Bearer {token}"},
    )
    monitor_id = create_resp.json()["id"]

    del_resp = await client.delete(
        f"/api/v1/monitors/{monitor_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert del_resp.status_code == 204

    get_resp = await client.get(
        f"/api/v1/monitors/{monitor_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert get_resp.status_code == 404


@pytest.mark.asyncio
async def test_monitor_invalid_url(client: AsyncClient) -> None:
    token = await _get_token(client, "invalid")
    resp = await client.post(
        "/api/v1/monitors/",
        json={"name": "Bad URL", "url": "not-a-url"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422
