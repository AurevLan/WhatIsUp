"""Tests for AlertSilence (T1-01)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_create_silence_for_one_monitor(client: AsyncClient, user_token: str) -> None:
    auth = _auth(user_token)
    m = (
        await client.post(
            "/api/v1/monitors/",
            json={"name": "Silenced", "url": "https://example.com"},
            headers=auth,
        )
    ).json()
    starts = datetime.now(UTC).isoformat()
    ends = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    resp = await client.post(
        "/api/v1/silences/",
        json={
            "name": "Cert renew",
            "reason": "tls rotation",
            "monitor_id": m["id"],
            "starts_at": starts,
            "ends_at": ends,
        },
        headers=auth,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["monitor_id"] == m["id"]
    assert body["name"] == "Cert renew"


@pytest.mark.asyncio
async def test_create_silence_global_when_monitor_id_null(
    client: AsyncClient, user_token: str
) -> None:
    auth = _auth(user_token)
    starts = datetime.now(UTC).isoformat()
    ends = (datetime.now(UTC) + timedelta(hours=2)).isoformat()
    resp = await client.post(
        "/api/v1/silences/",
        json={"name": "Global mute", "monitor_id": None, "starts_at": starts, "ends_at": ends},
        headers=auth,
    )
    assert resp.status_code == 201
    assert resp.json()["monitor_id"] is None


@pytest.mark.asyncio
async def test_create_silence_rejects_inverted_window(
    client: AsyncClient, user_token: str
) -> None:
    auth = _auth(user_token)
    starts = datetime.now(UTC).isoformat()
    ends = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    resp = await client.post(
        "/api/v1/silences/",
        json={"name": "Bad", "starts_at": starts, "ends_at": ends},
        headers=auth,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_list_only_own_silences(
    client: AsyncClient, user_token: str, admin_token: str
) -> None:
    starts = datetime.now(UTC).isoformat()
    ends = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    await client.post(
        "/api/v1/silences/",
        json={"name": "User mute", "starts_at": starts, "ends_at": ends},
        headers=_auth(user_token),
    )
    await client.post(
        "/api/v1/silences/",
        json={"name": "Admin mute", "starts_at": starts, "ends_at": ends},
        headers=_auth(admin_token),
    )

    user_list = (await client.get("/api/v1/silences/", headers=_auth(user_token))).json()
    admin_list = (await client.get("/api/v1/silences/", headers=_auth(admin_token))).json()

    user_names = {s["name"] for s in user_list}
    admin_names = {s["name"] for s in admin_list}
    assert "User mute" in user_names and "Admin mute" not in user_names
    assert "Admin mute" in admin_names and "User mute" not in admin_names


@pytest.mark.asyncio
async def test_delete_silence(client: AsyncClient, user_token: str) -> None:
    auth = _auth(user_token)
    starts = datetime.now(UTC).isoformat()
    ends = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    created = (
        await client.post(
            "/api/v1/silences/",
            json={"name": "To delete", "starts_at": starts, "ends_at": ends},
            headers=auth,
        )
    ).json()
    sid = created["id"]
    resp = await client.delete(f"/api/v1/silences/{sid}", headers=auth)
    assert resp.status_code == 204
    listing = (await client.get("/api/v1/silences/", headers=auth)).json()
    assert all(s["id"] != sid for s in listing)


@pytest.mark.asyncio
async def test_dispatch_skipped_when_silenced(
    db_session, admin_user, monkeypatch
) -> None:
    """A matching active silence shortcuts dispatch_alert before any IO."""
    from whatisup.models.alert import AlertChannel, AlertChannelType
    from whatisup.models.incident import Incident, IncidentScope
    from whatisup.models.monitor import Monitor
    from whatisup.models.silence import AlertSilence
    from whatisup.services.alert import dispatch_alert

    monitor = Monitor(name="silenced", url="http://x.example.com", owner_id=admin_user.id)
    db_session.add(monitor)
    await db_session.flush()

    incident = Incident(
        monitor_id=monitor.id, started_at=datetime.now(UTC),
        scope=IncidentScope.global_, affected_probe_ids=[],
    )
    db_session.add(incident)

    channel = AlertChannel(
        owner_id=admin_user.id,
        name="dummy", type=AlertChannelType.webhook, config={"url": "https://example.com"},
    )
    db_session.add(channel)

    now = datetime.now(UTC)
    silence = AlertSilence(
        owner_id=admin_user.id, name="active", monitor_id=monitor.id,
        starts_at=now - timedelta(minutes=5), ends_at=now + timedelta(hours=1),
    )
    db_session.add(silence)
    await db_session.commit()

    # Spy: replace the channel handler to detect any send.
    sent = []

    class SpyHandler:
        async def send(self, *args, **kwargs):
            sent.append(True)
            return "spy:sent"

    from whatisup.services import channels as ch_module
    monkeypatch.setitem(ch_module.CHANNEL_REGISTRY, "webhook", SpyHandler())

    await dispatch_alert(db_session, incident, channel, "incident_opened", ctx={})
    assert sent == []  # silenced → no dispatch
