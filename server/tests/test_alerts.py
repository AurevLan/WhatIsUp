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
async def test_create_signal_channel_invalid_recipient(
    client: AsyncClient, user_token: str,
) -> None:
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


# ── Alert matrix (conditions × channels per monitor) ─────────────────────────


@pytest.mark.asyncio
async def test_get_matrix_empty(client: AsyncClient, user_token: str) -> None:
    monitor_id, _ = await _create_monitor_and_channel(client, user_token)
    resp = await client.get(
        f"/api/v1/alerts/monitors/{monitor_id}/matrix", headers=_auth(user_token)
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["monitor_id"] == monitor_id
    assert data["rows"] == []


@pytest.mark.asyncio
async def test_put_matrix_creates_rules(client: AsyncClient, user_token: str) -> None:
    monitor_id, ch1 = await _create_monitor_and_channel(client, user_token)
    ch2 = (
        await client.post(
            "/api/v1/alerts/channels",
            json={
                "name": "Ch2",
                "type": "webhook",
                "config": {"url": "https://hooks.example.com/2"},
            },
            headers=_auth(user_token),
        )
    ).json()["id"]

    resp = await client.put(
        f"/api/v1/alerts/monitors/{monitor_id}/matrix",
        json={
            "rows": [
                {"condition": "any_down", "channel_ids": [ch1, ch2]},
                {
                    "condition": "response_time_above",
                    "channel_ids": [ch1],
                    "threshold_value": 2000,
                },
            ]
        },
        headers=_auth(user_token),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert len(data["rows"]) == 2
    conditions = {r["condition"] for r in data["rows"]}
    assert conditions == {"any_down", "response_time_above"}
    any_down = next(r for r in data["rows"] if r["condition"] == "any_down")
    assert {c["id"] for c in any_down["channels"]} == {ch1, ch2}


@pytest.mark.asyncio
async def test_put_matrix_upserts_and_removes(client: AsyncClient, user_token: str) -> None:
    monitor_id, ch1 = await _create_monitor_and_channel(client, user_token)

    # First PUT: two rows
    await client.put(
        f"/api/v1/alerts/monitors/{monitor_id}/matrix",
        json={
            "rows": [
                {"condition": "any_down", "channel_ids": [ch1]},
                {"condition": "all_down", "channel_ids": [ch1]},
            ]
        },
        headers=_auth(user_token),
    )

    # Second PUT: only any_down with updated params → all_down must be removed
    resp = await client.put(
        f"/api/v1/alerts/monitors/{monitor_id}/matrix",
        json={
            "rows": [
                {
                    "condition": "any_down",
                    "channel_ids": [ch1],
                    "min_duration_seconds": 120,
                    "enabled": False,
                }
            ]
        },
        headers=_auth(user_token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["rows"]) == 1
    row = data["rows"][0]
    assert row["condition"] == "any_down"
    assert row["min_duration_seconds"] == 120
    assert row["enabled"] is False


@pytest.mark.asyncio
async def test_put_matrix_rejects_duplicate_condition(
    client: AsyncClient, user_token: str
) -> None:
    monitor_id, ch1 = await _create_monitor_and_channel(client, user_token)
    resp = await client.put(
        f"/api/v1/alerts/monitors/{monitor_id}/matrix",
        json={
            "rows": [
                {"condition": "any_down", "channel_ids": [ch1]},
                {"condition": "any_down", "channel_ids": [ch1]},
            ]
        },
        headers=_auth(user_token),
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_put_matrix_rejects_empty_channels(
    client: AsyncClient, user_token: str
) -> None:
    monitor_id, _ = await _create_monitor_and_channel(client, user_token)
    resp = await client.put(
        f"/api/v1/alerts/monitors/{monitor_id}/matrix",
        json={"rows": [{"condition": "any_down", "channel_ids": []}]},
        headers=_auth(user_token),
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_put_matrix_persists_schedule(client: AsyncClient, user_token: str) -> None:
    monitor_id, ch1 = await _create_monitor_and_channel(client, user_token)
    schedule = {
        "timezone": "Europe/Paris",
        "days": [0, 1, 2, 3, 4],
        "start": "09:00",
        "end": "18:00",
        "offhours_suppress": True,
    }
    put_resp = await client.put(
        f"/api/v1/alerts/monitors/{monitor_id}/matrix",
        json={
            "rows": [
                {
                    "condition": "any_down",
                    "channel_ids": [ch1],
                    "schedule": schedule,
                }
            ]
        },
        headers=_auth(user_token),
    )
    assert put_resp.status_code == 200, put_resp.text

    get_resp = await client.get(
        f"/api/v1/alerts/monitors/{monitor_id}/matrix", headers=_auth(user_token)
    )
    assert get_resp.status_code == 200
    rows = get_resp.json()["rows"]
    assert len(rows) == 1
    assert rows[0]["schedule"] == schedule


@pytest.mark.asyncio
async def test_create_rule_with_tag_selector(client: AsyncClient, user_token: str) -> None:
    _, channel_id = await _create_monitor_and_channel(client, user_token)
    resp = await client.post(
        "/api/v1/alerts/rules",
        json={
            "condition": "any_down",
            "channel_ids": [channel_id],
            "tag_selector": ["env:prod", "team:backend"],
        },
        headers=_auth(user_token),
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["monitor_id"] is None
    assert data["group_id"] is None
    assert data["tag_selector"] == ["env:prod", "team:backend"]


@pytest.mark.asyncio
async def test_create_rule_without_target_rejected(
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
async def test_delete_tag_selector_rule(client: AsyncClient, user_token: str) -> None:
    _, channel_id = await _create_monitor_and_channel(client, user_token)
    create = await client.post(
        "/api/v1/alerts/rules",
        json={
            "condition": "any_down",
            "channel_ids": [channel_id],
            "tag_selector": ["env:prod"],
        },
        headers=_auth(user_token),
    )
    rule_id = create.json()["id"]
    resp = await client.delete(
        f"/api/v1/alerts/rules/{rule_id}", headers=_auth(user_token)
    )
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_matrix_unknown_monitor_404(client: AsyncClient, user_token: str) -> None:
    import uuid as _uuid

    resp = await client.get(
        f"/api/v1/alerts/monitors/{_uuid.uuid4()}/matrix", headers=_auth(user_token)
    )
    assert resp.status_code == 404
