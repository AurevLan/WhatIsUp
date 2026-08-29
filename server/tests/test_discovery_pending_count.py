"""Discovery pending-count — nav badge counter (plan E, E-3).

``GET /discovery/services/pending-count`` is the lightweight sibling of
``list_services`` polled every few seconds by the sidebar badge: same
visibility rule (``owner_id == me OR team_id IN my_teams``, superadmin
bypasses), but a bare ``COUNT(*)`` over ``proposed`` rows only — ``orphaned``
services already have their own badge (``useOrphanedMonitors``) and are not a
fresh proposal waiting on a decision.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.core.limiter import limiter
from whatisup.core.security import hash_password
from whatisup.models.discovery import DiscoveredService, DiscoverySource
from whatisup.models.team import TeamMembership, TeamRole
from whatisup.models.user import User

TEST_PASSWORD = "TestPassword123!"


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def stranger(db_session: AsyncSession) -> User:
    u = User(
        email="pending-count-stranger@test.com",
        username="pending-count-stranger",
        hashed_password=hash_password(TEST_PASSWORD),
        is_superadmin=False,
        can_create_monitors=True,
    )
    db_session.add(u)
    await db_session.flush()
    return u


@pytest_asyncio.fixture
async def stranger_token(client: AsyncClient, stranger: User) -> str:
    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": stranger.email, "password": TEST_PASSWORD},
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]


async def _register_probe(
    client: AsyncClient, admin_token: str, name: str = "probe-pending-count"
) -> str:
    resp = await client.post(
        "/api/v1/probes/register",
        json={"name": name, "location_name": "Paris"},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _make_source(
    db_session: AsyncSession,
    owner_id: uuid.UUID,
    probe_id: str,
    team_id: uuid.UUID | None = None,
) -> DiscoverySource:
    source = DiscoverySource(
        owner_id=owner_id,
        team_id=team_id,
        probe_id=uuid.UUID(probe_id),
        source_type="docker",
        params={},
    )
    db_session.add(source)
    await db_session.flush()
    return source


def _make_service(
    source: DiscoverySource, host: str, status_: str = "proposed"
) -> DiscoveredService:
    now = datetime.now(UTC)
    return DiscoveredService(
        source_id=source.id,
        host=host,
        port=80,
        proto="tcp",
        normalized_target=f"tcp://{host}:80",
        status=status_,
        first_seen_at=now,
        last_seen_at=now,
        status_changed_at=now,
    )


# ── Counting ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pending_count_zero_when_nothing_proposed(
    client: AsyncClient, user_token: str
) -> None:
    resp = await client.get("/api/v1/discovery/services/pending-count", headers=_auth(user_token))
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"count": 0}


@pytest.mark.asyncio
async def test_pending_count_counts_only_proposed(
    client: AsyncClient,
    user_token: str,
    admin_token: str,
    regular_user: User,
    db_session: AsyncSession,
) -> None:
    probe_id = await _register_probe(client, admin_token)
    source = await _make_source(db_session, regular_user.id, probe_id)
    db_session.add_all(
        [
            _make_service(source, "10.0.0.1", status_="proposed"),
            _make_service(source, "10.0.0.2", status_="proposed"),
            _make_service(source, "10.0.0.3", status_="accepted"),
            _make_service(source, "10.0.0.4", status_="dismissed"),
            _make_service(source, "10.0.0.5", status_="orphaned"),
        ]
    )
    await db_session.commit()

    resp = await client.get("/api/v1/discovery/services/pending-count", headers=_auth(user_token))
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"count": 2}


# ── Visibility ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pending_count_excludes_other_tenants(
    client: AsyncClient,
    user_token: str,
    stranger_token: str,
    admin_token: str,
    regular_user: User,
    db_session: AsyncSession,
) -> None:
    """A stranger sharing no team must see 0, never the owner's count —
    cross-tenant visibility must never leak through a bare counter."""
    probe_id = await _register_probe(client, admin_token)
    source = await _make_source(db_session, regular_user.id, probe_id)
    db_session.add(_make_service(source, "10.0.0.1", status_="proposed"))
    await db_session.commit()

    owner_resp = await client.get(
        "/api/v1/discovery/services/pending-count", headers=_auth(user_token)
    )
    assert owner_resp.json() == {"count": 1}

    stranger_resp = await client.get(
        "/api/v1/discovery/services/pending-count", headers=_auth(stranger_token)
    )
    assert stranger_resp.status_code == 200
    assert stranger_resp.json() == {"count": 0}


@pytest.mark.asyncio
async def test_pending_count_includes_team_scoped_sources(
    client: AsyncClient,
    user_token: str,
    stranger_token: str,
    stranger: User,
    admin_token: str,
    regular_user: User,
    db_session: AsyncSession,
) -> None:
    """A team member sees proposals from a team-scoped source, same rule as
    ``list_services``/``_visibility_filter``."""
    probe_id = await _register_probe(client, admin_token, "probe-pending-count-team")
    team_resp = await client.post(
        "/api/v1/teams/",
        json={"name": "Pending Count Team", "slug": "pending-count-team"},
        headers=_auth(user_token),
    )
    assert team_resp.status_code == 201, team_resp.text
    team_id = uuid.UUID(team_resp.json()["id"])
    db_session.add(TeamMembership(user_id=stranger.id, team_id=team_id, role=TeamRole.viewer))
    await db_session.flush()

    source = await _make_source(db_session, regular_user.id, probe_id, team_id=team_id)
    db_session.add(_make_service(source, "10.0.0.1", status_="proposed"))
    await db_session.commit()

    resp = await client.get(
        "/api/v1/discovery/services/pending-count", headers=_auth(stranger_token)
    )
    assert resp.status_code == 200
    assert resp.json() == {"count": 1}


@pytest.mark.asyncio
async def test_pending_count_superadmin_sees_everything(
    client: AsyncClient,
    admin_token: str,
    regular_user: User,
    db_session: AsyncSession,
) -> None:
    probe_id = await _register_probe(client, admin_token)
    source = await _make_source(db_session, regular_user.id, probe_id)
    db_session.add(_make_service(source, "10.0.0.1", status_="proposed"))
    await db_session.commit()

    resp = await client.get("/api/v1/discovery/services/pending-count", headers=_auth(admin_token))
    assert resp.status_code == 200
    assert resp.json() == {"count": 1}


# ── Rate limit gate ──────────────────────────────────────────────────────────


def test_pending_count_is_rate_limited() -> None:
    key = "whatisup.api.v1.discovery.count_pending_services"
    assert key in limiter._route_limits or key in limiter._dynamic_route_limits
