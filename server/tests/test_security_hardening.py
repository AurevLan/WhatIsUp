"""Tests for the 2026-06 security hardening pass.

- Tag mutation (PATCH/DELETE) restricted to superadmin (global shared pool).
- Custom metrics accessible via team membership (build_access_filter pattern).
- Maintenance window PATCH re-validates the reassigned monitor/group target.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.core.security import hash_password
from whatisup.models.user import User

TEST_PASSWORD = "TestPass1!"


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def user_b(db_session: AsyncSession) -> User:
    u = User(
        email="userb-sec@test.com",
        username="userb_sec",
        hashed_password=hash_password(TEST_PASSWORD),
        is_superadmin=False,
        can_create_monitors=True,
    )
    db_session.add(u)
    await db_session.flush()
    return u


@pytest_asyncio.fixture
async def user_b_token(client: AsyncClient, user_b: User) -> str:
    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": user_b.email, "password": TEST_PASSWORD},
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]


async def _create_monitor(client: AsyncClient, token: str, name: str, **extra) -> dict:
    resp = await client.post(
        "/api/v1/monitors/",
        json={"name": name, "url": "https://example.com", **extra},
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ── Tags: mutation is superadmin-only ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_regular_user_cannot_update_tag(client: AsyncClient, user_token: str) -> None:
    create = await client.post(
        "/api/v1/tags/", json={"name": "sec:patch"}, headers=_auth(user_token)
    )
    tag_id = create.json()["id"]
    resp = await client.patch(
        f"/api/v1/tags/{tag_id}", json={"name": "hijacked"}, headers=_auth(user_token)
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_regular_user_cannot_delete_tag(client: AsyncClient, user_token: str) -> None:
    create = await client.post(
        "/api/v1/tags/", json={"name": "sec:delete"}, headers=_auth(user_token)
    )
    tag_id = create.json()["id"]
    resp = await client.delete(f"/api/v1/tags/{tag_id}", headers=_auth(user_token))
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_superadmin_can_update_and_delete_tag(
    client: AsyncClient, user_token: str, admin_token: str
) -> None:
    create = await client.post(
        "/api/v1/tags/", json={"name": "sec:admin"}, headers=_auth(user_token)
    )
    tag_id = create.json()["id"]

    patched = await client.patch(
        f"/api/v1/tags/{tag_id}", json={"color": "#00ff00"}, headers=_auth(admin_token)
    )
    assert patched.status_code == 200
    assert patched.json()["color"] == "#00ff00"

    deleted = await client.delete(f"/api/v1/tags/{tag_id}", headers=_auth(admin_token))
    assert deleted.status_code == 204


# ── Custom metrics: team access ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_team_editor_can_push_and_read_metrics(
    client: AsyncClient, user_token: str, user_b: User, user_b_token: str
) -> None:
    """A team editor (not the owner) can push and read custom metrics."""
    team = await client.post(
        "/api/v1/teams/", json={"name": "Metrics Team"}, headers=_auth(user_token)
    )
    assert team.status_code == 201, team.text
    team_id = team.json()["id"]
    add = await client.post(
        f"/api/v1/teams/{team_id}/members",
        json={"user_id": str(user_b.id), "role": "editor"},
        headers=_auth(user_token),
    )
    assert add.status_code in (200, 201), add.text

    monitor = await _create_monitor(client, user_token, "Team metrics", team_id=team_id)

    push = await client.post(
        f"/api/v1/metrics/{monitor['id']}",
        json={"metric_name": "queue_depth", "value": 12.0},
        headers=_auth(user_b_token),
    )
    assert push.status_code == 201, push.text

    listed = await client.get(f"/api/v1/metrics/{monitor['id']}", headers=_auth(user_b_token))
    assert listed.status_code == 200
    assert any(m["metric_name"] == "queue_depth" for m in listed.json())

    summary = await client.get(
        f"/api/v1/metrics/{monitor['id']}/summary", headers=_auth(user_b_token)
    )
    assert summary.status_code == 200


@pytest.mark.asyncio
async def test_non_member_cannot_push_metrics(
    client: AsyncClient, user_token: str, user_b_token: str
) -> None:
    monitor = await _create_monitor(client, user_token, "Private metrics")
    push = await client.post(
        f"/api/v1/metrics/{monitor['id']}",
        json={"metric_name": "x", "value": 1.0},
        headers=_auth(user_b_token),
    )
    assert push.status_code == 403


@pytest.mark.asyncio
async def test_owner_can_still_push_metrics(client: AsyncClient, user_token: str) -> None:
    monitor = await _create_monitor(client, user_token, "Own metrics")
    push = await client.post(
        f"/api/v1/metrics/{monitor['id']}",
        json={"metric_name": "y", "value": 2.0},
        headers=_auth(user_token),
    )
    assert push.status_code == 201


# ── Maintenance windows: PATCH re-validates target ────────────────────────────


@pytest.mark.asyncio
async def test_maintenance_patch_cannot_reassign_to_foreign_monitor(
    client: AsyncClient, user_token: str, user_b_token: str
) -> None:
    """PATCH must reject reassigning the window to a monitor the user doesn't own."""
    foreign = await _create_monitor(client, user_b_token, "Foreign monitor")
    own = await _create_monitor(client, user_token, "Own monitor")

    window = await client.post(
        "/api/v1/maintenance/",
        json={
            "name": "Nightly",
            "monitor_id": own["id"],
            "starts_at": "2026-06-12T00:00:00Z",
            "ends_at": "2026-06-12T02:00:00Z",
        },
        headers=_auth(user_token),
    )
    assert window.status_code == 201, window.text
    window_id = window.json()["id"]

    patched = await client.patch(
        f"/api/v1/maintenance/{window_id}",
        json={
            "name": "Nightly",
            "monitor_id": foreign["id"],
            "starts_at": "2026-06-12T00:00:00Z",
            "ends_at": "2026-06-12T02:00:00Z",
        },
        headers=_auth(user_token),
    )
    assert patched.status_code == 403


@pytest.mark.asyncio
async def test_maintenance_patch_own_target_still_works(
    client: AsyncClient, user_token: str
) -> None:
    own = await _create_monitor(client, user_token, "Own monitor 2")
    window = await client.post(
        "/api/v1/maintenance/",
        json={
            "name": "Weekly",
            "monitor_id": own["id"],
            "starts_at": "2026-06-12T00:00:00Z",
            "ends_at": "2026-06-12T02:00:00Z",
        },
        headers=_auth(user_token),
    )
    assert window.status_code == 201, window.text
    patched = await client.patch(
        f"/api/v1/maintenance/{window.json()['id']}",
        json={
            "name": "Weekly renamed",
            "monitor_id": own["id"],
            "starts_at": "2026-06-12T00:00:00Z",
            "ends_at": "2026-06-12T03:00:00Z",
        },
        headers=_auth(user_token),
    )
    assert patched.status_code == 200
    assert patched.json()["name"] == "Weekly renamed"
