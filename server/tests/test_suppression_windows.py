"""Tests for the merged suppression window (plan cap v2, 6d — ex-AlertSilence,
now MaintenanceWindow.is_maintenance=False).

Behaviour preserved from the old AlertSilence CRUD (T1-01), now exercised
through ``/api/v1/maintenance/``:
- a monitor-scoped silence
- a catch-all silence (no monitor_id, no group_id — "every monitor I own"),
  now legal only when is_maintenance=False
- inverted window rejected
- list is scoped to the caller (owner OR their team — a superset of the old
  strictly-per-owner behaviour, since the survivor table already supported
  team scoping)
- delete
- dispatch shortcut in services.alert.dispatch_alert

New behaviour introduced by the merge:
- is_maintenance=True still requires a monitor_id or group_id (the old
  MaintenanceWindow constraint)
- is_maintenance=False does NOT suppress incident creation
  (services.maintenance.is_in_maintenance), unlike is_maintenance=True
"""

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
        "/api/v1/maintenance/",
        json={
            "name": "Cert renew",
            "description": "tls rotation",
            "monitor_id": m["id"],
            "starts_at": starts,
            "ends_at": ends,
            "is_maintenance": False,
        },
        headers=auth,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["monitor_id"] == m["id"]
    assert body["name"] == "Cert renew"
    assert body["is_maintenance"] is False


@pytest.mark.asyncio
async def test_create_silence_global_when_no_target(client: AsyncClient, user_token: str) -> None:
    """A pure silence may target nothing at all — "every monitor I own",
    the old AlertSilence catch-all. This must stay illegal for a real
    maintenance window (see test_maintenance_requires_target_below)."""
    auth = _auth(user_token)
    starts = datetime.now(UTC).isoformat()
    ends = (datetime.now(UTC) + timedelta(hours=2)).isoformat()
    resp = await client.post(
        "/api/v1/maintenance/",
        json={
            "name": "Global mute",
            "monitor_id": None,
            "starts_at": starts,
            "ends_at": ends,
            "is_maintenance": False,
        },
        headers=auth,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["monitor_id"] is None


@pytest.mark.asyncio
async def test_maintenance_requires_target(client: AsyncClient, user_token: str) -> None:
    """Unlike a silence, is_maintenance=True (the default) still requires a
    monitor or group target — the pre-6d MaintenanceWindow constraint."""
    auth = _auth(user_token)
    starts = datetime.now(UTC).isoformat()
    ends = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    resp = await client.post(
        "/api/v1/maintenance/",
        json={"name": "No target", "starts_at": starts, "ends_at": ends},
        headers=auth,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_silence_rejects_inverted_window(client: AsyncClient, user_token: str) -> None:
    auth = _auth(user_token)
    starts = datetime.now(UTC).isoformat()
    ends = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    resp = await client.post(
        "/api/v1/maintenance/",
        json={"name": "Bad", "starts_at": starts, "ends_at": ends, "is_maintenance": False},
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
        "/api/v1/maintenance/",
        json={"name": "User mute", "starts_at": starts, "ends_at": ends, "is_maintenance": False},
        headers=_auth(user_token),
    )
    await client.post(
        "/api/v1/maintenance/",
        json={"name": "Admin mute", "starts_at": starts, "ends_at": ends, "is_maintenance": False},
        headers=_auth(admin_token),
    )

    user_list = (await client.get("/api/v1/maintenance/", headers=_auth(user_token))).json()
    user_names = {s["name"] for s in user_list}
    # A regular (non-superadmin) user still only sees their own — or their
    # team's — windows, same isolation as the old per-owner AlertSilence list.
    assert "User mute" in user_names and "Admin mute" not in user_names


@pytest.mark.asyncio
async def test_delete_silence(client: AsyncClient, user_token: str) -> None:
    auth = _auth(user_token)
    starts = datetime.now(UTC).isoformat()
    ends = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    created = (
        await client.post(
            "/api/v1/maintenance/",
            json={
                "name": "To delete",
                "starts_at": starts,
                "ends_at": ends,
                "is_maintenance": False,
            },
            headers=auth,
        )
    ).json()
    wid = created["id"]
    resp = await client.delete(f"/api/v1/maintenance/{wid}", headers=auth)
    assert resp.status_code == 204
    listing = (await client.get("/api/v1/maintenance/", headers=auth)).json()
    assert all(w["id"] != wid for w in listing)


@pytest.mark.asyncio
async def test_dispatch_skipped_when_silenced(db_session, admin_user, monkeypatch) -> None:
    """A matching active silence (is_maintenance=False) shortcuts
    dispatch_alert before any IO — same guarantee as the old AlertSilence."""
    from whatisup.models.alert import AlertChannel, AlertChannelType
    from whatisup.models.incident import Incident, IncidentScope
    from whatisup.models.maintenance import MaintenanceWindow
    from whatisup.models.monitor import Monitor
    from whatisup.services.alert import dispatch_alert

    monitor = Monitor(name="silenced", url="http://x.example.com", owner_id=admin_user.id)
    db_session.add(monitor)
    await db_session.flush()

    incident = Incident(
        monitor_id=monitor.id,
        started_at=datetime.now(UTC),
        scope=IncidentScope.global_,
        affected_probe_ids=[],
    )
    db_session.add(incident)

    channel = AlertChannel(
        owner_id=admin_user.id,
        name="dummy",
        type=AlertChannelType.webhook,
        config={"url": "https://example.com"},
    )
    db_session.add(channel)

    now = datetime.now(UTC)
    silence = MaintenanceWindow(
        owner_id=admin_user.id,
        name="active",
        monitor_id=monitor.id,
        starts_at=now - timedelta(minutes=5),
        ends_at=now + timedelta(hours=1),
        is_maintenance=False,
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


@pytest.mark.asyncio
async def test_pure_silence_does_not_suppress_incident_creation(db_session, admin_user) -> None:
    """The whole point of the is_maintenance bit: a plain silence must not
    exclude downtime from uptime — only a real maintenance window does."""
    from whatisup.models.maintenance import MaintenanceWindow
    from whatisup.models.monitor import Monitor
    from whatisup.services.maintenance import is_in_maintenance

    monitor = Monitor(name="not-in-maintenance", url="http://y.example.com", owner_id=admin_user.id)
    db_session.add(monitor)
    await db_session.flush()

    now = datetime.now(UTC)
    silence = MaintenanceWindow(
        owner_id=admin_user.id,
        name="just a silence",
        monitor_id=monitor.id,
        starts_at=now - timedelta(minutes=5),
        ends_at=now + timedelta(hours=1),
        is_maintenance=False,
    )
    db_session.add(silence)
    await db_session.commit()

    assert await is_in_maintenance(db_session, monitor.id, None) is False

    silence.is_maintenance = True
    await db_session.commit()

    assert await is_in_maintenance(db_session, monitor.id, None) is True
