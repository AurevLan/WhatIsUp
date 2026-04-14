"""Tests for tag CRUD endpoints."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_list_tags_empty(client: AsyncClient, user_token: str) -> None:
    resp = await client.get("/api/v1/tags/", headers=_auth(user_token))
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_create_and_list_tag(client: AsyncClient, user_token: str) -> None:
    create = await client.post(
        "/api/v1/tags/",
        json={"name": "env:prod", "color": "#ff0000"},
        headers=_auth(user_token),
    )
    assert create.status_code == 201
    assert create.json()["name"] == "env:prod"

    listed = await client.get("/api/v1/tags/", headers=_auth(user_token))
    assert any(t["name"] == "env:prod" for t in listed.json())


@pytest.mark.asyncio
async def test_create_tag_is_idempotent(client: AsyncClient, user_token: str) -> None:
    first = await client.post(
        "/api/v1/tags/", json={"name": "team:backend"}, headers=_auth(user_token)
    )
    second = await client.post(
        "/api/v1/tags/", json={"name": "team:backend"}, headers=_auth(user_token)
    )
    assert first.json()["id"] == second.json()["id"]


@pytest.mark.asyncio
async def test_delete_tag(client: AsyncClient, user_token: str) -> None:
    create = await client.post(
        "/api/v1/tags/", json={"name": "to_delete"}, headers=_auth(user_token)
    )
    tag_id = create.json()["id"]
    resp = await client.delete(f"/api/v1/tags/{tag_id}", headers=_auth(user_token))
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_assign_tag_to_monitor(client: AsyncClient, user_token: str) -> None:
    tag_resp = await client.post(
        "/api/v1/tags/", json={"name": "env:staging"}, headers=_auth(user_token)
    )
    tag_id = tag_resp.json()["id"]

    mon_resp = await client.post(
        "/api/v1/monitors/",
        json={
            "name": "Tagged",
            "url": "https://example.com",
            "tag_ids": [tag_id],
        },
        headers=_auth(user_token),
    )
    assert mon_resp.status_code == 201, mon_resp.text
    assert any(t["id"] == tag_id for t in mon_resp.json()["tags"])
