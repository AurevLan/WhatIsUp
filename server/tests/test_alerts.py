"""Tests for alert channel and rule endpoints."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ── Channels ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_alert_channel(client: AsyncClient, user_token: str) -> None:
    resp = await client.post(
        "/api/v1/alerts/channels",
        json={"name": "My Webhook", "type": "webhook", "config": {"url": "https://hooks.example.com/abc"}},
        headers=_auth(user_token),
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "My Webhook"
    assert data["type"] == "webhook"


@pytest.mark.asyncio
async def test_list_alert_channels(client: AsyncClient, user_token: str) -> None:
    await client.post(
        "/api/v1/alerts/channels",
        json={"name": "Ch1", "type": "webhook", "config": {"url": "https://hooks.example.com/1"}},
        headers=_auth(user_token),
    )
    resp = await client.get("/api/v1/alerts/channels", headers=_auth(user_token))
    assert resp.status_code == 200
    assert len(resp.json()) >= 1


@pytest.mark.asyncio
async def test_delete_alert_channel(client: AsyncClient, user_token: str) -> None:
    create = await client.post(
        "/api/v1/alerts/channels",
        json={"name": "ToDelete", "type": "webhook", "config": {"url": "https://hooks.example.com/d"}},
        headers=_auth(user_token),
    )
    channel_id = create.json()["id"]

    del_resp = await client.delete(
        f"/api/v1/alerts/channels/{channel_id}", headers=_auth(user_token)
    )
    assert del_resp.status_code == 204


@pytest.mark.asyncio
async def test_delete_other_user_channel_returns_404(
    client: AsyncClient, user_token: str, admin_token: str
) -> None:
    create = await client.post(
        "/api/v1/alerts/channels",
        json={"name": "AdminCh", "type": "webhook", "config": {"url": "https://hooks.example.com/a"}},
        headers=_auth(admin_token),
    )
    channel_id = create.json()["id"]

    resp = await client.delete(
        f"/api/v1/alerts/channels/{channel_id}", headers=_auth(user_token)
    )
    assert resp.status_code == 404


# ── Signal channel ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_signal_channel(client: AsyncClient, user_token: str) -> None:
    resp = await client.post(
        "/api/v1/alerts/channels",
        json={
            "name": "Signal Alerts",
            "type": "signal",
            "config": {
                "api_url": "https://signal-api.example.com",
                "sender_number": "+33612345678",
                "recipients": ["+33698765432"],
            },
        },
        headers=_auth(user_token),
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["type"] == "signal"
    assert data["name"] == "Signal Alerts"


@pytest.mark.asyncio
async def test_create_signal_channel_invalid_phone(client: AsyncClient, user_token: str) -> None:
    resp = await client.post(
        "/api/v1/alerts/channels",
        json={
            "name": "Bad Signal",
            "type": "signal",
            "config": {
                "api_url": "https://signal-api.example.com",
                "sender_number": "not-a-phone",
                "recipients": ["+33698765432"],
            },
        },
        headers=_auth(user_token),
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_signal_channel_invalid_recipient(client: AsyncClient, user_token: str) -> None:
    resp = await client.post(
        "/api/v1/alerts/channels",
        json={
            "name": "Bad Signal",
            "type": "signal",
            "config": {
                "api_url": "https://signal-api.example.com",
                "sender_number": "+33612345678",
                "recipients": ["invalid"],
            },
        },
        headers=_auth(user_token),
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_signal_channel_invalid_url(client: AsyncClient, user_token: str) -> None:
    resp = await client.post(
        "/api/v1/alerts/channels",
        json={
            "name": "Bad Signal",
            "type": "signal",
            "config": {
                "api_url": "ftp://invalid",
                "sender_number": "+33612345678",
                "recipients": ["+33698765432"],
            },
        },
        headers=_auth(user_token),
    )
    assert resp.status_code == 422


# ── Rules ─────────────────────────────────────────────────────────────────────


async def _create_monitor_and_channel(client: AsyncClient, token: str) -> tuple[str, str]:
    mon = await client.post(
        "/api/v1/monitors/",
        json={"name": "Alert Mon", "url": "https://example.com"},
        headers={"Authorization": f"Bearer {token}"},
    )
    ch = await client.post(
        "/api/v1/alerts/channels",
        json={"name": "RuleCh", "type": "webhook", "config": {"url": "https://hooks.example.com/r"}},
        headers={"Authorization": f"Bearer {token}"},
    )
    return mon.json()["id"], ch.json()["id"]


@pytest.mark.asyncio
async def test_create_alert_rule(client: AsyncClient, user_token: str) -> None:
    monitor_id, channel_id = await _create_monitor_and_channel(client, user_token)

    resp = await client.post(
        "/api/v1/alerts/rules",
        json={
            "monitor_id": monitor_id,
            "condition": "any_down",
            "channel_ids": [channel_id],
        },
        headers=_auth(user_token),
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["condition"] == "any_down"
    assert any(ch["id"] == channel_id for ch in data["channels"])


@pytest.mark.asyncio
async def test_create_rule_requires_monitor_or_group(
    client: AsyncClient, user_token: str
) -> None:
    _, channel_id = await _create_monitor_and_channel(client, user_token)

    resp = await client.post(
        "/api/v1/alerts/rules",
        json={"condition": "any_down", "channel_ids": [channel_id]},
        headers=_auth(user_token),
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_list_alert_rules(client: AsyncClient, user_token: str) -> None:
    monitor_id, channel_id = await _create_monitor_and_channel(client, user_token)
    await client.post(
        "/api/v1/alerts/rules",
        json={"monitor_id": monitor_id, "condition": "any_down", "channel_ids": [channel_id]},
        headers=_auth(user_token),
    )
    resp = await client.get("/api/v1/alerts/rules", headers=_auth(user_token))
    assert resp.status_code == 200
    assert len(resp.json()) >= 1


@pytest.mark.asyncio
async def test_update_alert_rule(client: AsyncClient, user_token: str) -> None:
    monitor_id, channel_id = await _create_monitor_and_channel(client, user_token)
    create = await client.post(
        "/api/v1/alerts/rules",
        json={"monitor_id": monitor_id, "condition": "any_down", "channel_ids": [channel_id]},
        headers=_auth(user_token),
    )
    rule_id = create.json()["id"]

    resp = await client.patch(
        f"/api/v1/alerts/rules/{rule_id}",
        json={"enabled": False},
        headers=_auth(user_token),
    )
    assert resp.status_code == 200
    assert resp.json()["enabled"] is False


@pytest.mark.asyncio
async def test_delete_alert_rule(client: AsyncClient, user_token: str) -> None:
    monitor_id, channel_id = await _create_monitor_and_channel(client, user_token)
    create = await client.post(
        "/api/v1/alerts/rules",
        json={"monitor_id": monitor_id, "condition": "any_down", "channel_ids": [channel_id]},
        headers=_auth(user_token),
    )
    rule_id = create.json()["id"]

    del_resp = await client.delete(
        f"/api/v1/alerts/rules/{rule_id}", headers=_auth(user_token)
    )
    assert del_resp.status_code == 204


# ── Events ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_alert_events_empty(client: AsyncClient, user_token: str) -> None:
    resp = await client.get("/api/v1/alerts/events", headers=_auth(user_token))
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_alerts_require_auth(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/alerts/channels")
    assert resp.status_code == 401
