"""Security audit Lot 1 — regression tests for SEC-H1/M1/M3/M5 and BUG-P0."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.core.security import hash_password
from whatisup.models.incident import Incident, IncidentScope
from whatisup.models.maintenance import MaintenanceWindow
from whatisup.models.monitor import Monitor
from whatisup.models.probe import Probe
from whatisup.models.result import CheckResult, CheckStatus
from whatisup.models.user import User
from whatisup.services.incident import process_check_result
from whatisup.services.web_push import (
    InvalidPushEndpoint,
    send_push_to_user,
    validate_push_endpoint,
)

TEST_PASSWORD = "TestPass1!"


class _EventCollector:
    def __init__(self) -> None:
        self.events: list[dict] = []

    async def __call__(self, event: dict) -> None:
        self.events.append(event)


async def _mk_user(db: AsyncSession, email: str) -> User:
    u = User(
        email=email,
        username=email.split("@")[0],
        hashed_password=hash_password(TEST_PASSWORD),
        can_create_monitors=True,
    )
    db.add(u)
    await db.flush()
    return u


async def _token(client: AsyncClient, email: str) -> str:
    resp = await client.post(
        "/api/v1/auth/login", data={"username": email, "password": TEST_PASSWORD}
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]


# ── SEC-H1: Web Push SSRF guard ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_validate_push_endpoint_rejects_non_https() -> None:
    with pytest.raises(InvalidPushEndpoint):
        await validate_push_endpoint("http://updates.push.services.mozilla.com/abc")


@pytest.mark.asyncio
async def test_validate_push_endpoint_rejects_ssrf_host() -> None:
    # Internal target masquerading as an endpoint — not an allowed push host.
    with pytest.raises(InvalidPushEndpoint):
        await validate_push_endpoint("https://169.254.169.254/latest/meta-data/")
    with pytest.raises(InvalidPushEndpoint):
        await validate_push_endpoint("https://internal.corp.local/hook")


@pytest.mark.asyncio
async def test_validate_push_endpoint_accepts_known_provider(monkeypatch) -> None:
    # Allowlisted host: the DNS-resolving SSRF step is stubbed to stay offline.
    mock = AsyncMock()
    monkeypatch.setattr("whatisup.services.web_push.validate_webhook_url", mock)
    await validate_push_endpoint("https://fcm.googleapis.com/fcm/send/abc123")
    mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_push_skips_stored_invalid_endpoint(
    service_db: AsyncSession, monkeypatch
) -> None:
    """A stored endpoint that predates the guard must not be dispatched."""
    from whatisup.models.web_push import WebPushSubscription

    user = await _mk_user(service_db, "push@test.com")
    service_db.add(
        WebPushSubscription(
            user_id=user.id,
            endpoint="http://169.254.169.254/steal",
            p256dh="p",
            auth="a",
        )
    )
    await service_db.flush()

    monkeypatch.setattr(
        "whatisup.services.web_push.get_settings",
        lambda: SimpleNamespace(
            vapid_private_key="priv", vapid_public_key="pub", vapid_contact_email="o@x.io"
        ),
    )
    sent: list = []
    monkeypatch.setattr(
        "whatisup.services.web_push._send_one",
        lambda *a, **k: sent.append(a),
    )
    await send_push_to_user(service_db, user.id, "t", "b")
    assert sent == []  # invalid endpoint skipped, never dispatched


# ── SEC-M1: cross-tenant group_id / team_id assignment ────────────────────────


@pytest.mark.asyncio
async def test_create_monitor_rejects_foreign_group(
    client: AsyncClient, admin_token: str, user_token: str
) -> None:
    grp = await client.post(
        "/api/v1/groups/",
        json={"name": "admin-only group"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert grp.status_code == 201
    group_id = grp.json()["id"]

    resp = await client.post(
        "/api/v1/monitors/",
        json={"name": "evil", "url": "https://example.com", "group_id": group_id},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_create_monitor_rejects_foreign_team(client: AsyncClient, user_token: str) -> None:
    import uuid

    resp = await client.post(
        "/api/v1/monitors/",
        json={
            "name": "evil",
            "url": "https://example.com",
            "team_id": str(uuid.uuid4()),
        },
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 403


# ── SEC-M3: team admin cannot grant a role above their own ────────────────────


@pytest.mark.asyncio
async def test_admin_member_cannot_add_owner(client: AsyncClient, db_session: AsyncSession) -> None:
    await _mk_user(db_session, "owner@m3.com")
    admin = await _mk_user(db_session, "admin@m3.com")
    victim = await _mk_user(db_session, "victim@m3.com")
    owner_tok = await _token(client, "owner@m3.com")
    admin_tok = await _token(client, "admin@m3.com")

    team = await client.post(
        "/api/v1/teams/",
        json={"name": "T", "slug": "t-m3"},
        headers={"Authorization": f"Bearer {owner_tok}"},
    )
    team_id = team.json()["id"]

    r = await client.post(
        f"/api/v1/teams/{team_id}/members",
        json={"user_id": str(admin.id), "role": "admin"},
        headers={"Authorization": f"Bearer {owner_tok}"},
    )
    assert r.status_code == 201

    # The admin tries to escalate a new member to owner → forbidden.
    r = await client.post(
        f"/api/v1/teams/{team_id}/members",
        json={"user_id": str(victim.id), "role": "owner"},
        headers={"Authorization": f"Bearer {admin_tok}"},
    )
    assert r.status_code == 403

    # …but may still add at or below their own level.
    r = await client.post(
        f"/api/v1/teams/{team_id}/members",
        json={"user_id": str(victim.id), "role": "editor"},
        headers={"Authorization": f"Bearer {admin_tok}"},
    )
    assert r.status_code == 201


# ── SEC-M5: probe diagnostics must be tied to a monitor the probe serves ──────


@pytest_asyncio.fixture
async def probe_with_key(db_session: AsyncSession) -> Probe:
    import bcrypt

    key_hash = bcrypt.hashpw(b"wiu_diag_probe_key", bcrypt.gensalt(rounds=4)).decode()
    p = Probe(name="diag-probe", location_name="DC", api_key_hash=key_hash)
    db_session.add(p)
    await db_session.flush()
    return p


@pytest.mark.asyncio
async def test_push_diagnostics_rejects_unserved_monitor(
    client: AsyncClient, db_session: AsyncSession, probe_with_key: Probe
) -> None:
    user = await _mk_user(db_session, "m5@test.com")
    mon = Monitor(name="m5", url="http://e.com", owner_id=user.id)
    db_session.add(mon)
    await db_session.flush()
    incident = Incident(
        monitor_id=mon.id,
        started_at=datetime.now(UTC),
        scope=IncidentScope.global_,
        affected_probe_ids=[],
    )
    db_session.add(incident)
    await db_session.flush()

    body = {
        "incident_id": str(incident.id),
        "results": [
            {
                "kind": "traceroute",
                "payload": {},
                "collected_at": datetime.now(UTC).isoformat(),
            }
        ],
    }
    headers = {"X-Probe-Api-Key": "wiu_diag_probe_key"}

    # Probe has never reported on this monitor → forbidden.
    r = await client.post("/api/v1/probes/diagnostics", json=body, headers=headers)
    assert r.status_code == 403

    # Once the probe has a result for the monitor, the same push is accepted.
    db_session.add(
        CheckResult(
            monitor_id=mon.id,
            probe_id=probe_with_key.id,
            checked_at=datetime.now(UTC),
            status=CheckStatus.up,
        )
    )
    await db_session.flush()
    r = await client.post("/api/v1/probes/diagnostics", json=body, headers=headers)
    assert r.status_code == 202


# ── BUG-P0: a maintenance-suppressed incident must alert once maintenance ends ─


@pytest.mark.asyncio
async def test_suppressed_incident_promoted_after_maintenance(
    service_db: AsyncSession,
) -> None:
    user = await _mk_user(service_db, "p0@test.com")
    mon = Monitor(name="p0", url="http://e.com", owner_id=user.id)
    probe = Probe(name="p0-probe", location_name="DC", api_key_hash="x")
    service_db.add_all([mon, probe])
    await service_db.flush()

    now = datetime.now(UTC)
    window = MaintenanceWindow(
        name="mw",
        owner_id=user.id,
        monitor_id=mon.id,
        starts_at=now - timedelta(hours=1),
        ends_at=now + timedelta(hours=1),
        suppress_alerts=True,
    )
    service_db.add(window)
    await service_db.flush()

    async def _down() -> CheckResult:
        r = CheckResult(
            monitor_id=mon.id,
            probe_id=probe.id,
            checked_at=datetime.now(UTC),
            status=CheckStatus.down,
        )
        service_db.add(r)
        await service_db.flush()
        return r

    # 1) Down during maintenance → suppressed incident, no opening alert.
    c1 = _EventCollector()
    await process_check_result(service_db, await _down(), c1)
    inc = (
        await service_db.execute(select(Incident).where(Incident.monitor_id == mon.id))
    ).scalar_one()
    assert inc.dependency_suppressed is True
    assert not any(e["type"] == "incident_opened" for e in c1.events)

    # 2) Maintenance ends, monitor still down → incident must be promoted.
    window.ends_at = datetime.now(UTC) - timedelta(minutes=1)
    await service_db.flush()

    c2 = _EventCollector()
    await process_check_result(service_db, await _down(), c2)
    await service_db.refresh(inc)
    assert inc.dependency_suppressed is False
    assert inc.resolved_at is None
    assert any(e["type"] == "incident_opened" for e in c2.events)
