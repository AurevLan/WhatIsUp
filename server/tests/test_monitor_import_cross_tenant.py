"""F2 — the monitor import must not mass-assign a foreign ``group_id``.

``POST /monitors/import`` takes raw JSON and whitelists ``group_id`` as a
config field, so before the fix a user could attach their own monitor to
another tenant's group — making it render on the victim's public status page.
The create/update endpoints have always guarded this with
``assert_can_assign_group``; the import path must do the same.

Also covers the adjacent finding that the import path stored secret scenario
variables verbatim instead of encrypting them at rest.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.core.security import hash_password
from whatisup.models.monitor import Monitor, MonitorGroup
from whatisup.models.user import User


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _victim_group(db: AsyncSession) -> MonitorGroup:
    victim = User(
        email="victim@test.com",
        username="victimuser",
        hashed_password=hash_password("x" * 12),
        can_create_monitors=True,
    )
    db.add(victim)
    await db.flush()
    group = MonitorGroup(name="Victim status page", owner_id=victim.id)
    db.add(group)
    await db.flush()
    return group


@pytest.mark.asyncio
async def test_import_rejects_foreign_group_id(
    client: AsyncClient, user_token: str, db_session: AsyncSession
) -> None:
    """A monitor pointing at another tenant's group is refused, not imported."""
    group = await _victim_group(db_session)

    resp = await client.post(
        "/api/v1/monitors/import",
        json=[{"name": "Poison", "url": "https://evil.example.com", "group_id": str(group.id)}],
        headers=_auth(user_token),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["imported"] == 0
    assert body["updated"] == 0
    assert len(body["errors"]) == 1
    assert "group" in body["errors"][0].lower()

    # Nothing landed in the victim's group.
    monitors = (
        (await db_session.execute(select(Monitor).where(Monitor.group_id == group.id)))
        .scalars()
        .all()
    )
    assert monitors == []


@pytest.mark.asyncio
async def test_import_update_path_cannot_move_monitor_into_foreign_group(
    client: AsyncClient, user_token: str, db_session: AsyncSession
) -> None:
    """The upsert-by-name branch is guarded too, not just creation."""
    group = await _victim_group(db_session)

    created = await client.post(
        "/api/v1/monitors/",
        json={"name": "Mine", "url": "https://mine.example.com"},
        headers=_auth(user_token),
    )
    assert created.status_code == 201, created.text
    monitor_id = uuid.UUID(created.json()["id"])

    resp = await client.post(
        "/api/v1/monitors/import",
        json=[{"name": "Mine", "url": "https://mine.example.com", "group_id": str(group.id)}],
        headers=_auth(user_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["updated"] == 0
    assert resp.json()["errors"]

    monitor = (
        await db_session.execute(select(Monitor).where(Monitor.id == monitor_id))
    ).scalar_one()
    assert monitor.group_id is None


@pytest.mark.asyncio
async def test_import_accepts_own_group_id(
    client: AsyncClient, user_token: str, db_session: AsyncSession
) -> None:
    """The guard must not break the legitimate case."""
    created = await client.post(
        "/api/v1/groups/",
        json={"name": "My group"},
        headers=_auth(user_token),
    )
    assert created.status_code == 201, created.text
    group_id = created.json()["id"]

    resp = await client.post(
        "/api/v1/monitors/import",
        json=[{"name": "Grouped", "url": "https://ok.example.com", "group_id": group_id}],
        headers=_auth(user_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"imported": 1, "updated": 0, "errors": []}

    monitor = (
        await db_session.execute(select(Monitor).where(Monitor.name == "Grouped"))
    ).scalar_one()
    assert str(monitor.group_id) == group_id


@pytest.mark.asyncio
async def test_import_rejects_malformed_group_id(client: AsyncClient, user_token: str) -> None:
    resp = await client.post(
        "/api/v1/monitors/import",
        json=[{"name": "Bad", "url": "https://bad.example.com", "group_id": "not-a-uuid"}],
        headers=_auth(user_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["imported"] == 0
    assert "group_id" in resp.json()["errors"][0]


@pytest.mark.asyncio
async def test_import_encrypts_secret_scenario_variables(
    client: AsyncClient,
    user_token: str,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Secret scenario variables must never be persisted verbatim by the import."""
    from cryptography.fernet import Fernet

    from whatisup.core.config import get_settings

    monkeypatch.setattr(get_settings(), "fernet_key", Fernet.generate_key().decode())

    resp = await client.post(
        "/api/v1/monitors/import",
        json=[
            {
                "name": "Scenario",
                "url": "https://app.example.com",
                "check_type": "scenario",
                "scenario_variables": [
                    {"name": "PASSWORD", "value": "S3cretPass", "secret": True},
                    {"name": "USERNAME", "value": "alice", "secret": False},
                ],
            }
        ],
        headers=_auth(user_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["imported"] == 1

    monitor = (
        await db_session.execute(select(Monitor).where(Monitor.name == "Scenario"))
    ).scalar_one()
    stored = {v["name"]: v["value"] for v in monitor.scenario_variables}
    assert stored["PASSWORD"] != "S3cretPass"
    assert stored["USERNAME"] == "alice"

    from whatisup.core.security import decrypt_scenario_variables

    decrypted = decrypt_scenario_variables(monitor.scenario_variables)
    assert {v["name"]: v["value"] for v in decrypted}["PASSWORD"] == "S3cretPass"
