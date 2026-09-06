"""Plan cap V2, étape 5a — scheduled maintenance on the public status page.

Decisions under test (see plan_cap_v2.md § 5a and CLAUDE.md):
- The public payload announces the *fact* and the *window* of a maintenance
  that concerns this group's monitors — nothing more by default.
- `MaintenanceWindow.name` and `.description` were written assuming they were
  internal (e.g. "migration PG16 prod-db-02") and must never appear in the
  public payload, even when a window is active. Only the optional,
  operator-written `public_message` is ever shown.
- A window on another group's monitor (or another group entirely) must never
  appear on this group's public page.
- Only current + upcoming windows are published — one already ended drops out.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.models.maintenance import MaintenanceWindow
from whatisup.models.user import User


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _make_group_and_monitor(
    client: AsyncClient, token: str, *, slug: str, monitor_name: str
) -> tuple[str, str]:
    grp = (
        await client.post(
            "/api/v1/groups/",
            json={"name": slug, "public_slug": slug},
            headers=_auth(token),
        )
    ).json()
    mon = (
        await client.post(
            "/api/v1/monitors/",
            json={
                "name": monitor_name,
                "url": "https://example.com",
                "group_id": grp["id"],
            },
            headers=_auth(token),
        )
    ).json()
    return grp["id"], mon["id"]


async def _create_window(
    client: AsyncClient,
    token: str,
    *,
    name: str,
    description: str | None,
    public_message: str | None,
    monitor_id: str | None = None,
    group_id: str | None = None,
    starts_at: datetime,
    ends_at: datetime,
) -> dict:
    resp = await client.post(
        "/api/v1/maintenance/",
        json={
            "name": name,
            "description": description,
            "public_message": public_message,
            "monitor_id": monitor_id,
            "group_id": group_id,
            "starts_at": starts_at.isoformat(),
            "ends_at": ends_at.isoformat(),
        },
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_active_window_is_published_with_window_and_message(
    client: AsyncClient, user_token: str
) -> None:
    _, monitor_id = await _make_group_and_monitor(
        client, user_token, slug="pub-maint-active", monitor_name="MaintMon"
    )
    now = datetime.now(UTC)
    starts = now - timedelta(minutes=5)
    ends = now + timedelta(hours=1)
    await _create_window(
        client,
        user_token,
        name="migration PG16 prod-db-02",
        description="internal runbook details",
        public_message="We are performing scheduled maintenance.",
        monitor_id=monitor_id,
        starts_at=starts,
        ends_at=ends,
    )

    resp = await client.get("/api/v1/public/pages/pub-maint-active/status")
    assert resp.status_code == 200
    windows = resp.json()["maintenance_windows"]
    assert len(windows) == 1
    w = windows[0]
    assert w["monitor_id"] == monitor_id
    assert w["message"] == "We are performing scheduled maintenance."
    assert w["starts_at"].startswith(starts.date().isoformat())
    assert w["ends_at"].startswith(ends.date().isoformat())


@pytest.mark.asyncio
async def test_window_without_public_message_still_publishes_the_fact(
    client: AsyncClient, user_token: str
) -> None:
    _, monitor_id = await _make_group_and_monitor(
        client, user_token, slug="pub-maint-nomsg", monitor_name="MaintMon2"
    )
    now = datetime.now(UTC)
    await _create_window(
        client,
        user_token,
        name="prod-db-02 patching",
        description=None,
        public_message=None,
        monitor_id=monitor_id,
        starts_at=now - timedelta(minutes=1),
        ends_at=now + timedelta(hours=1),
    )

    resp = await client.get("/api/v1/public/pages/pub-maint-nomsg/status")
    assert resp.status_code == 200
    windows = resp.json()["maintenance_windows"]
    assert len(windows) == 1
    assert windows[0]["message"] is None
    assert "prod-db-02" not in resp.text


@pytest.mark.asyncio
async def test_group_wide_window_is_published(client: AsyncClient, user_token: str) -> None:
    group_id, _ = await _make_group_and_monitor(
        client, user_token, slug="pub-maint-group", monitor_name="MaintMon3"
    )
    now = datetime.now(UTC)
    await _create_window(
        client,
        user_token,
        name="datacenter-wide maintenance",
        description=None,
        public_message="Planned network maintenance.",
        group_id=group_id,
        starts_at=now - timedelta(minutes=1),
        ends_at=now + timedelta(hours=2),
    )

    resp = await client.get("/api/v1/public/pages/pub-maint-group/status")
    assert resp.status_code == 200
    windows = resp.json()["maintenance_windows"]
    assert len(windows) == 1
    assert windows[0]["monitor_id"] is None
    assert windows[0]["message"] == "Planned network maintenance."


@pytest.mark.asyncio
async def test_upcoming_window_is_published(client: AsyncClient, user_token: str) -> None:
    _, monitor_id = await _make_group_and_monitor(
        client, user_token, slug="pub-maint-upcoming", monitor_name="MaintMon4"
    )
    now = datetime.now(UTC)
    await _create_window(
        client,
        user_token,
        name="future window",
        description=None,
        public_message=None,
        monitor_id=monitor_id,
        starts_at=now + timedelta(hours=2),
        ends_at=now + timedelta(hours=3),
    )

    resp = await client.get("/api/v1/public/pages/pub-maint-upcoming/status")
    assert resp.status_code == 200
    assert len(resp.json()["maintenance_windows"]) == 1


@pytest.mark.asyncio
async def test_ended_window_is_not_published(client: AsyncClient, user_token: str) -> None:
    _, monitor_id = await _make_group_and_monitor(
        client, user_token, slug="pub-maint-ended", monitor_name="MaintMon5"
    )
    now = datetime.now(UTC)
    await _create_window(
        client,
        user_token,
        name="past window",
        description=None,
        public_message=None,
        monitor_id=monitor_id,
        starts_at=now - timedelta(hours=3),
        ends_at=now - timedelta(hours=1),
    )

    resp = await client.get("/api/v1/public/pages/pub-maint-ended/status")
    assert resp.status_code == 200
    assert resp.json()["maintenance_windows"] == []


@pytest.mark.asyncio
async def test_window_on_another_group_monitor_is_not_leaked(
    client: AsyncClient, user_token: str
) -> None:
    _, other_monitor_id = await _make_group_and_monitor(
        client, user_token, slug="pub-maint-other", monitor_name="OtherMon"
    )
    _, _ = await _make_group_and_monitor(
        client, user_token, slug="pub-maint-victim", monitor_name="VictimMon"
    )
    now = datetime.now(UTC)
    await _create_window(
        client,
        user_token,
        name="other group's window",
        description=None,
        public_message="Should never appear on the victim page.",
        monitor_id=other_monitor_id,
        starts_at=now - timedelta(minutes=1),
        ends_at=now + timedelta(hours=1),
    )

    resp = await client.get("/api/v1/public/pages/pub-maint-victim/status")
    assert resp.status_code == 200
    assert resp.json()["maintenance_windows"] == []
    assert "Should never appear on the victim page." not in resp.text

    # Sanity: it *does* show up on its own page.
    own_resp = await client.get("/api/v1/public/pages/pub-maint-other/status")
    assert len(own_resp.json()["maintenance_windows"]) == 1


@pytest.mark.asyncio
async def test_public_status_never_leaks_maintenance_name_or_description(
    client: AsyncClient, user_token: str, db_session: AsyncSession
) -> None:
    """Watertight test, modeled on
    test_public_status_network_verdict.py::test_public_status_never_leaks_operator_identity.

    Whatever the window's content, its `name` and `description` — written by
    the operator assuming they were private — must never appear in the raw
    JSON text of the public payload, active or upcoming, monitor-scoped or
    group-wide.
    """
    group_id, monitor_id = await _make_group_and_monitor(
        client, user_token, slug="pub-maint-leakproof", monitor_name="LeakproofMaintMon"
    )
    now = datetime.now(UTC)

    secret_name = "migration PG16 prod-db-02 SECRET"
    secret_description = "internal runbook: rotate credentials on host db-02.internal"

    windows = [
        MaintenanceWindow(
            id=uuid.uuid4(),
            name=secret_name,
            description=secret_description,
            public_message=None,
            owner_id=uuid.uuid4(),  # overwritten below via the API-created group's owner
            monitor_id=uuid.UUID(monitor_id),
            starts_at=now - timedelta(minutes=1),
            ends_at=now + timedelta(hours=1),
        ),
        MaintenanceWindow(
            id=uuid.uuid4(),
            name=secret_name + " (group)",
            description=secret_description + " (group)",
            public_message="Public-facing sentence only.",
            owner_id=uuid.uuid4(),
            group_id=uuid.UUID(group_id),
            starts_at=now + timedelta(hours=2),
            ends_at=now + timedelta(hours=3),
        ),
    ]

    # Fetch the real owner_id (the regular_user behind user_token) so the FK
    # constraint holds — inserting directly bypasses the API's own owner_id
    # assignment, so it must be set correctly by hand here.
    owner = (
        await db_session.execute(select(User).where(User.email == "user@test.com"))
    ).scalar_one()
    for w in windows:
        w.owner_id = owner.id
        db_session.add(w)
    await db_session.commit()

    resp = await client.get("/api/v1/public/pages/pub-maint-leakproof/status")
    assert resp.status_code == 200
    raw = resp.text

    assert secret_name not in raw
    assert secret_description not in raw
    assert "SECRET" not in raw
    assert "internal runbook" not in raw
    assert "Public-facing sentence only." in raw
