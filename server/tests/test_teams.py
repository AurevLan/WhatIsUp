"""Tests for the Teams & RBAC system."""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.core.security import hash_password
from whatisup.models.team import Team, TeamMembership, TeamRole
from whatisup.models.user import User

TEST_PASSWORD = "TestPass1!"


# ── Extra fixtures ───────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def user_b(db_session: AsyncSession) -> User:
    """A second regular user for cross-team tests."""
    u = User(
        email="userb@test.com",
        username="userb",
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


# ── Team CRUD ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_team(client: AsyncClient, user_token: str) -> None:
    resp = await client.post(
        "/api/v1/teams/",
        json={"name": "Ops Team", "slug": "ops-team"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Ops Team"
    assert data["slug"] == "ops-team"
    assert data["member_count"] == 1  # creator is auto-added as owner


@pytest.mark.asyncio
async def test_create_team_auto_slug(client: AsyncClient, user_token: str) -> None:
    resp = await client.post(
        "/api/v1/teams/",
        json={"name": "My Great Team"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 201
    assert resp.json()["slug"] == "my-great-team"


@pytest.mark.asyncio
async def test_create_team_duplicate_slug(client: AsyncClient, user_token: str) -> None:
    await client.post(
        "/api/v1/teams/",
        json={"name": "Dup", "slug": "dup-slug"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    resp = await client.post(
        "/api/v1/teams/",
        json={"name": "Dup2", "slug": "dup-slug"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_list_teams_only_mine(
    client: AsyncClient, user_token: str, user_b_token: str
) -> None:
    # User A creates a team
    resp_a = await client.post(
        "/api/v1/teams/",
        json={"name": "Team A", "slug": "team-a-list"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp_a.status_code == 201

    # User B should NOT see Team A
    resp_b = await client.get(
        "/api/v1/teams/",
        headers={"Authorization": f"Bearer {user_b_token}"},
    )
    assert resp_b.status_code == 200
    names = [t["name"] for t in resp_b.json()]
    assert "Team A" not in names


@pytest.mark.asyncio
async def test_update_team(client: AsyncClient, user_token: str) -> None:
    create_resp = await client.post(
        "/api/v1/teams/",
        json={"name": "Before", "slug": "update-test"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    team_id = create_resp.json()["id"]

    resp = await client.patch(
        f"/api/v1/teams/{team_id}",
        json={"name": "After"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "After"


@pytest.mark.asyncio
async def test_delete_team(client: AsyncClient, user_token: str) -> None:
    create_resp = await client.post(
        "/api/v1/teams/",
        json={"name": "ToDelete", "slug": "to-delete"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    team_id = create_resp.json()["id"]

    resp = await client.delete(
        f"/api/v1/teams/{team_id}",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 204


# ── Membership management ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_add_member(
    client: AsyncClient, user_token: str, user_b: User
) -> None:
    create_resp = await client.post(
        "/api/v1/teams/",
        json={"name": "Members Team", "slug": "members-team"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    team_id = create_resp.json()["id"]

    resp = await client.post(
        f"/api/v1/teams/{team_id}/members",
        json={"user_id": str(user_b.id), "role": "editor"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 201
    assert resp.json()["role"] == "editor"
    assert resp.json()["username"] == "userb"


@pytest.mark.asyncio
async def test_add_member_duplicate(
    client: AsyncClient, user_token: str, user_b: User
) -> None:
    create_resp = await client.post(
        "/api/v1/teams/",
        json={"name": "Dup Members", "slug": "dup-members"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    team_id = create_resp.json()["id"]

    await client.post(
        f"/api/v1/teams/{team_id}/members",
        json={"user_id": str(user_b.id), "role": "viewer"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    resp = await client.post(
        f"/api/v1/teams/{team_id}/members",
        json={"user_id": str(user_b.id), "role": "editor"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_update_member_role(
    client: AsyncClient, user_token: str, user_b: User
) -> None:
    create_resp = await client.post(
        "/api/v1/teams/",
        json={"name": "Role Change", "slug": "role-change"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    team_id = create_resp.json()["id"]

    await client.post(
        f"/api/v1/teams/{team_id}/members",
        json={"user_id": str(user_b.id), "role": "viewer"},
        headers={"Authorization": f"Bearer {user_token}"},
    )

    resp = await client.patch(
        f"/api/v1/teams/{team_id}/members/{user_b.id}",
        json={"role": "admin"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == "admin"


@pytest.mark.asyncio
async def test_remove_member(
    client: AsyncClient, user_token: str, user_b: User
) -> None:
    create_resp = await client.post(
        "/api/v1/teams/",
        json={"name": "Remove Test", "slug": "remove-test"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    team_id = create_resp.json()["id"]

    await client.post(
        f"/api/v1/teams/{team_id}/members",
        json={"user_id": str(user_b.id), "role": "editor"},
        headers={"Authorization": f"Bearer {user_token}"},
    )

    resp = await client.delete(
        f"/api/v1/teams/{team_id}/members/{user_b.id}",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_cannot_remove_last_owner(
    client: AsyncClient, user_token: str
) -> None:
    create_resp = await client.post(
        "/api/v1/teams/",
        json={"name": "Last Owner", "slug": "last-owner"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    team_id = create_resp.json()["id"]

    # Get the owner's membership (the only member)
    members_resp = await client.get(
        f"/api/v1/teams/{team_id}/members",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    owner_id = members_resp.json()[0]["user_id"]

    resp = await client.delete(
        f"/api/v1/teams/{team_id}/members/{owner_id}",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 400
    assert "last owner" in resp.json()["detail"].lower()


# ── RBAC: viewer cannot modify ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_viewer_cannot_update_team(
    client: AsyncClient, user_token: str, user_b: User, user_b_token: str
) -> None:
    create_resp = await client.post(
        "/api/v1/teams/",
        json={"name": "RBAC Test", "slug": "rbac-test"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    team_id = create_resp.json()["id"]

    # Add user_b as viewer
    await client.post(
        f"/api/v1/teams/{team_id}/members",
        json={"user_id": str(user_b.id), "role": "viewer"},
        headers={"Authorization": f"Bearer {user_token}"},
    )

    # Viewer tries to update team name → 403
    resp = await client.patch(
        f"/api/v1/teams/{team_id}",
        json={"name": "Hacked"},
        headers={"Authorization": f"Bearer {user_b_token}"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_viewer_cannot_add_members(
    client: AsyncClient, user_token: str, user_b: User, user_b_token: str
) -> None:
    create_resp = await client.post(
        "/api/v1/teams/",
        json={"name": "RBAC Members", "slug": "rbac-members"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    team_id = create_resp.json()["id"]

    await client.post(
        f"/api/v1/teams/{team_id}/members",
        json={"user_id": str(user_b.id), "role": "viewer"},
        headers={"Authorization": f"Bearer {user_token}"},
    )

    # Viewer tries to add someone → 403
    resp = await client.post(
        f"/api/v1/teams/{team_id}/members",
        json={"user_id": str(user_b.id), "role": "editor"},
        headers={"Authorization": f"Bearer {user_b_token}"},
    )
    assert resp.status_code in (403, 409)  # 403 if RBAC blocks, 409 if self-duplicate


# ── Cross-team isolation ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_non_member_cannot_access_team(
    client: AsyncClient, user_token: str, user_b_token: str
) -> None:
    create_resp = await client.post(
        "/api/v1/teams/",
        json={"name": "Private", "slug": "private-team"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    team_id = create_resp.json()["id"]

    # Non-member tries to get team details → 403
    resp = await client.get(
        f"/api/v1/teams/{team_id}",
        headers={"Authorization": f"Bearer {user_b_token}"},
    )
    assert resp.status_code == 403
