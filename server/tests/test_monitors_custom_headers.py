"""Tests for the per-monitor custom_headers field."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_monitor_with_custom_headers(client: AsyncClient, user_token: str) -> None:
    resp = await client.post(
        "/api/v1/monitors/",
        json={
            "name": "WithHeaders",
            "url": "https://example.com",
            "custom_headers": {
                "User-Agent": "Mozilla/5.0 (compat)",
                "X-Trace-Id": "abc123",
            },
        },
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["custom_headers"]["User-Agent"] == "Mozilla/5.0 (compat)"
    assert data["custom_headers"]["X-Trace-Id"] == "abc123"


@pytest.mark.asyncio
async def test_update_monitor_custom_headers(client: AsyncClient, user_token: str) -> None:
    created = (
        await client.post(
            "/api/v1/monitors/",
            json={"name": "UH", "url": "https://example.com"},
            headers={"Authorization": f"Bearer {user_token}"},
        )
    ).json()
    monitor_id = created["id"]

    resp = await client.patch(
        f"/api/v1/monitors/{monitor_id}",
        json={"custom_headers": {"User-Agent": "Bot/1.0"}},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["custom_headers"] == {"User-Agent": "Bot/1.0"}

    cleared = await client.patch(
        f"/api/v1/monitors/{monitor_id}",
        json={"custom_headers": None},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert cleared.status_code == 200
    assert cleared.json()["custom_headers"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "headers",
    [
        {"Host": "example.org"},  # blacklisted
        {"Content-Length": "0"},  # blacklisted
        {"connection": "keep-alive"},  # blacklisted (case-insensitive)
        {"Bad Header": "x"},  # invalid name (space)
        {"X-Empty": ""},  # empty value
        {"X-Long": "x" * 501},  # value too long
        {"a" * 101: "v"},  # name too long
    ],
)
async def test_create_monitor_rejects_bad_headers(
    client: AsyncClient, user_token: str, headers: dict[str, str]
) -> None:
    resp = await client.post(
        "/api/v1/monitors/",
        json={"name": "Bad", "url": "https://example.com", "custom_headers": headers},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_create_monitor_rejects_too_many_headers(
    client: AsyncClient, user_token: str
) -> None:
    too_many = {f"X-Header-{i}": "v" for i in range(21)}
    resp = await client.post(
        "/api/v1/monitors/",
        json={"name": "TooMany", "url": "https://example.com", "custom_headers": too_many},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 422, resp.text
