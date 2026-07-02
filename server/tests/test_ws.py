"""Tests for the WebSocket dashboard/public endpoints and ConnectionManager.

The dashboard auth protocol (auth-by-message, never ?token= in the URL) is a
hard security rule — these tests pin it.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.websockets import WebSocketDisconnect

from whatisup.api.v1.ws import (
    MAX_CONNECTIONS_PER_IP,
    SUPERADMIN_SCOPE,
    ConnectionManager,
    _compute_dashboard_scope,
    _compute_public_scope,
)
from whatisup.core.database import get_db
from whatisup.core.security import create_access_token, create_refresh_token
from whatisup.main import app
from whatisup.models.monitor import Monitor, MonitorGroup
from whatisup.models.team import Team, TeamMembership, TeamRole
from whatisup.models.user import User

# ── ConnectionManager unit tests ──────────────────────────────────────────────


def _fake_ws() -> AsyncMock:
    ws = AsyncMock()
    ws.accept = AsyncMock()
    ws.send_text = AsyncMock()
    return ws


@pytest.mark.asyncio
async def test_manager_enforces_per_ip_limit() -> None:
    manager = ConnectionManager()
    sockets = [_fake_ws() for _ in range(MAX_CONNECTIONS_PER_IP + 1)]

    for ws in sockets[:MAX_CONNECTIONS_PER_IP]:
        assert await manager.connect(ws, client_ip="1.2.3.4") is True

    # One more from the same IP is rejected without accept()
    extra = sockets[-1]
    assert await manager.connect(extra, client_ip="1.2.3.4") is False
    extra.accept.assert_not_called()

    # A different IP is still fine
    other = _fake_ws()
    assert await manager.connect(other, client_ip="5.6.7.8") is True


@pytest.mark.asyncio
async def test_manager_disconnect_frees_ip_slot() -> None:
    manager = ConnectionManager()
    sockets = []
    for _ in range(MAX_CONNECTIONS_PER_IP):
        ws = _fake_ws()
        assert await manager.connect(ws, client_ip="1.2.3.4") is True
        sockets.append(ws)

    await manager.disconnect(sockets[0])

    ws_new = _fake_ws()
    assert await manager.connect(ws_new, client_ip="1.2.3.4") is True


@pytest.mark.asyncio
async def test_manager_broadcast_drops_dead_connections() -> None:
    manager = ConnectionManager()
    alive = _fake_ws()
    dead = _fake_ws()
    dead.send_text = AsyncMock(side_effect=RuntimeError("gone"))
    await manager.connect(alive, client_ip="1.1.1.1")
    await manager.connect(dead, client_ip="2.2.2.2")
    # Authorize both as superadmin dashboards so the (monitor-less) event reaches them.
    await manager.authorize(alive, "dashboard", SUPERADMIN_SCOPE)
    await manager.authorize(dead, "dashboard", SUPERADMIN_SCOPE)

    await manager.broadcast({"type": "check_result"})

    alive.send_text.assert_awaited_once_with(json.dumps({"type": "check_result"}))
    assert dead not in manager._connections
    assert alive in manager._connections


@pytest.mark.asyncio
async def test_redis_subscriber_closes_pubsub_on_crash(monkeypatch) -> None:
    """Regression: a crashed listen() must release the pubsub connection.

    redis-py 8.0.0 times out idle pubsub reads after 5s; without aclose()
    every crash leaked one pool connection until the pool was dry and every
    Redis call (login included) failed with MaxConnectionsError.
    """
    import whatisup.api.v1.ws as ws_module

    pubsub = AsyncMock()

    async def _crashing_listen():
        raise TimeoutError("Timeout reading from redis:6379")
        yield  # pragma: no cover — makes this an async generator

    pubsub.listen = _crashing_listen
    redis = MagicMock()
    redis.pubsub = MagicMock(return_value=pubsub)
    monkeypatch.setattr(ws_module, "get_redis", lambda: redis)
    # Break the retry loop after the first crash
    monkeypatch.setattr(ws_module.asyncio, "sleep", AsyncMock(side_effect=asyncio.CancelledError))

    with pytest.raises(asyncio.CancelledError):
        await ws_module._redis_subscriber()

    pubsub.aclose.assert_awaited_once()


# ── Dashboard WS auth protocol ────────────────────────────────────────────────


@pytest.fixture
def ws_client(db_session: AsyncSession, fake_redis) -> TestClient:
    """Sync TestClient (httpx ASGITransport has no WebSocket support).

    The routes reach the DB only through ``ws_module._scope_session`` (a
    short-lived session, never held across the keep-alive loop). We do NOT wire
    the real async ``db_session`` into it here: TestClient runs the route on its
    own event loop, and touching the test-loop-bound aiosqlite connection from
    there deadlocks teardown. DB-dependent handshake tests instead inject a
    lightweight fake via :func:`_fake_scope_session`; the tenant-scoping logic
    itself is exercised directly (no TestClient) against ``db_session``.
    """
    import whatisup.core.redis as redis_module

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    redis_module._redis = fake_redis
    yield TestClient(app)
    app.dependency_overrides.clear()
    redis_module._redis = None


class _FakeResult:
    def __init__(self, value) -> None:
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _FakeScopeSession:
    """Minimal stand-in for the scope session used by the WS routes.

    ``execute(...).scalar_one_or_none()`` returns a canned value (a stub user or
    group, or ``None``). Superadmin stubs short-circuit ``_compute_dashboard_scope``
    before any monitor query, so a single ``execute`` is all the routes need here.
    """

    def __init__(self, value) -> None:
        self._value = value

    async def execute(self, _stmt):
        return _FakeResult(self._value)


def _fake_scope_session(monkeypatch, value) -> None:
    """Patch ws._scope_session to yield a fake session returning *value*."""
    from contextlib import asynccontextmanager

    import whatisup.api.v1.ws as ws_module

    @asynccontextmanager
    async def _cm():
        yield _FakeScopeSession(value)

    monkeypatch.setattr(ws_module, "_scope_session", _cm)


def test_ws_dashboard_valid_auth_keeps_connection(ws_client: TestClient, monkeypatch) -> None:
    import uuid
    from types import SimpleNamespace

    # Superadmin stub → scope resolves to "all" with a single user lookup.
    user = SimpleNamespace(id=uuid.uuid4(), is_active=True, is_superadmin=True)
    _fake_scope_session(monkeypatch, user)

    token = create_access_token(str(user.id))
    with ws_client.websocket_connect("/ws/dashboard") as ws:
        ws.send_text(json.dumps({"type": "auth", "token": token}))
        # Connection stays open: a ping frame is accepted without error
        ws.send_text("ping")


def test_ws_dashboard_rejects_unknown_user(ws_client: TestClient, monkeypatch) -> None:
    """A syntactically valid JWT for a user that no longer exists is rejected.

    Scoping requires loading the user; a deleted/revoked user's stale token must
    not open a (scoped) dashboard socket.
    """
    import uuid

    _fake_scope_session(monkeypatch, None)  # user lookup → None

    token = create_access_token(str(uuid.uuid4()))
    with ws_client.websocket_connect("/ws/dashboard") as ws:
        ws.send_text(json.dumps({"type": "auth", "token": token}))
        closed = ws.receive()
        assert closed["type"] == "websocket.close"
        assert closed["code"] == 4001


def test_ws_dashboard_rejects_bad_token(ws_client: TestClient) -> None:
    with ws_client.websocket_connect("/ws/dashboard") as ws:
        ws.send_text(json.dumps({"type": "auth", "token": "not-a-jwt"}))
        closed = ws.receive()
        assert closed["type"] == "websocket.close"
        assert closed["code"] == 4001


def test_ws_dashboard_rejects_refresh_token(ws_client: TestClient) -> None:
    """A refresh token must not be accepted where an access token is expected."""
    refresh = create_refresh_token("user-1")
    with ws_client.websocket_connect("/ws/dashboard") as ws:
        ws.send_text(json.dumps({"type": "auth", "token": refresh}))
        closed = ws.receive()
        assert closed["type"] == "websocket.close"
        assert closed["code"] == 4001


def test_ws_dashboard_rejects_non_auth_first_frame(ws_client: TestClient) -> None:
    with ws_client.websocket_connect("/ws/dashboard") as ws:
        ws.send_text(json.dumps({"type": "subscribe", "topic": "all"}))
        closed = ws.receive()
        assert closed["type"] == "websocket.close"
        assert closed["code"] == 4001


def test_ws_dashboard_rejects_invalid_json(ws_client: TestClient) -> None:
    with ws_client.websocket_connect("/ws/dashboard") as ws:
        ws.send_text("not json {")
        closed = ws.receive()
        assert closed["type"] == "websocket.close"
        assert closed["code"] == 4001


# ── Public WS slug validation ─────────────────────────────────────────────────


def test_ws_public_unknown_slug_closed(ws_client: TestClient, monkeypatch) -> None:
    _fake_scope_session(monkeypatch, None)  # group lookup → None
    # The route closes before accepting → the handshake itself fails with 4004
    with pytest.raises(WebSocketDisconnect) as exc_info:  # noqa: SIM117
        with ws_client.websocket_connect("/ws/public/unknown-slug"):
            pass
    assert exc_info.value.code == 4004


# ── Tenant scoping — ConnectionManager fan-out filter (finding audit M1) ───────


@pytest.mark.asyncio
async def test_broadcast_filters_by_monitor_scope() -> None:
    """A dashboard scoped to m1 gets m1's incident; a peer scoped to m2 does not."""
    manager = ConnectionManager()
    a = _fake_ws()
    b = _fake_ws()
    await manager.connect(a, client_ip="1.1.1.1")
    await manager.connect(b, client_ip="2.2.2.2")
    await manager.authorize(a, "dashboard", {"m1"})
    await manager.authorize(b, "dashboard", {"m2"})

    await manager.broadcast({"type": "incident_opened", "monitor_id": "m1"})

    a.send_text.assert_awaited_once()
    b.send_text.assert_not_called()


@pytest.mark.asyncio
async def test_broadcast_superadmin_scope_receives_all() -> None:
    manager = ConnectionManager()
    su = _fake_ws()
    await manager.connect(su, client_ip="1.1.1.1")
    await manager.authorize(su, "dashboard", SUPERADMIN_SCOPE)

    await manager.broadcast({"type": "incident_opened", "monitor_id": "any-monitor"})

    su.send_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_broadcast_unauthenticated_receives_nothing() -> None:
    """A connected-but-not-yet-authorized socket must never receive events."""
    manager = ConnectionManager()
    ws = _fake_ws()
    await manager.connect(ws, client_ip="1.1.1.1")  # never authorized

    await manager.broadcast({"type": "incident_opened", "monitor_id": "m1"})

    ws.send_text.assert_not_called()


@pytest.mark.asyncio
async def test_broadcast_public_socket_only_group_monitors() -> None:
    manager = ConnectionManager()
    pub = _fake_ws()
    await manager.connect(pub, client_ip="1.1.1.1")
    await manager.authorize(pub, "public", {"mG"})

    await manager.broadcast({"type": "incident_opened", "monitor_id": "mG"})
    pub.send_text.assert_awaited_once()

    pub.send_text.reset_mock()
    await manager.broadcast({"type": "incident_opened", "monitor_id": "other-tenant"})
    pub.send_text.assert_not_called()


@pytest.mark.asyncio
async def test_broadcast_global_event_dashboard_only() -> None:
    """Events without a monitor_id reach dashboards, never anonymous public sockets."""
    manager = ConnectionManager()
    dash = _fake_ws()
    pub = _fake_ws()
    await manager.connect(dash, client_ip="1.1.1.1")
    await manager.connect(pub, client_ip="2.2.2.2")
    await manager.authorize(dash, "dashboard", {"m1"})
    await manager.authorize(pub, "public", {"m1"})

    await manager.broadcast({"type": "global_announcement"})  # no monitor_id

    dash.send_text.assert_awaited_once()
    pub.send_text.assert_not_called()


# ── Tenant scoping — scope computation from the DB authorization model ─────────


async def _mk_user(db: AsyncSession, email: str, *, superadmin: bool = False) -> User:
    u = User(
        email=email,
        username=email.split("@")[0],
        hashed_password="x",
        is_superadmin=superadmin,
        is_active=True,
    )
    db.add(u)
    await db.flush()
    return u


async def _mk_monitor(
    db: AsyncSession,
    owner_id,
    name: str,
    *,
    group_id=None,
    team_id=None,
) -> Monitor:
    m = Monitor(
        name=name,
        url="http://example.com",
        owner_id=owner_id,
        group_id=group_id,
        team_id=team_id,
    )
    db.add(m)
    await db.flush()
    return m


@pytest.mark.asyncio
async def test_dashboard_scope_owner_isolation(db_session: AsyncSession) -> None:
    a = await _mk_user(db_session, "scope-a@ws.com")
    b = await _mk_user(db_session, "scope-b@ws.com")
    ma = await _mk_monitor(db_session, a.id, "scope-ma")
    mb = await _mk_monitor(db_session, b.id, "scope-mb")

    scope_a = await _compute_dashboard_scope(db_session, a)

    assert str(ma.id) in scope_a
    assert str(mb.id) not in scope_a


@pytest.mark.asyncio
async def test_dashboard_scope_superadmin_is_all(db_session: AsyncSession) -> None:
    su = await _mk_user(db_session, "scope-su@ws.com", superadmin=True)
    scope = await _compute_dashboard_scope(db_session, su)
    assert scope is SUPERADMIN_SCOPE  # None → everything


@pytest.mark.asyncio
async def test_dashboard_scope_includes_team_monitors(db_session: AsyncSession) -> None:
    owner = await _mk_user(db_session, "scope-town@ws.com")
    member = await _mk_user(db_session, "scope-tmem@ws.com")
    team = Team(name="scope-team", slug="scope-team-ws")
    db_session.add(team)
    await db_session.flush()
    db_session.add(TeamMembership(user_id=member.id, team_id=team.id, role=TeamRole.viewer))
    await db_session.flush()
    mt = await _mk_monitor(db_session, owner.id, "scope-mt", team_id=team.id)

    scope = await _compute_dashboard_scope(db_session, member)

    assert str(mt.id) in scope


@pytest.mark.asyncio
async def test_public_scope_only_group_monitors(db_session: AsyncSession) -> None:
    owner = await _mk_user(db_session, "scope-pown@ws.com")
    group = MonitorGroup(name="scope-g", owner_id=owner.id, public_slug="scope-statusx")
    db_session.add(group)
    await db_session.flush()
    mg = await _mk_monitor(db_session, owner.id, "scope-mg", group_id=group.id)
    mfree = await _mk_monitor(db_session, owner.id, "scope-mfree")

    scope = await _compute_public_scope(db_session, group.id)

    assert scope == {str(mg.id)}
    assert str(mfree.id) not in scope


@pytest.mark.asyncio
async def test_end_to_end_tenant_isolation(db_session: AsyncSession) -> None:
    """The four required scenarios wired against the real authorization model.

    user A ⊥ user B · superadmin sees all · public slug X ⊂ group X ·
    team member sees the team's monitors.
    """
    a = await _mk_user(db_session, "e2e-a@ws.com")
    b = await _mk_user(db_session, "e2e-b@ws.com")
    su = await _mk_user(db_session, "e2e-su@ws.com", superadmin=True)
    owner = await _mk_user(db_session, "e2e-own@ws.com")
    member = await _mk_user(db_session, "e2e-mem@ws.com")

    team = Team(name="e2e-team", slug="e2e-team-ws")
    db_session.add(team)
    await db_session.flush()
    db_session.add(TeamMembership(user_id=member.id, team_id=team.id, role=TeamRole.viewer))
    await db_session.flush()
    group = MonitorGroup(name="e2e-g", owner_id=owner.id, public_slug="e2e-statusy")
    db_session.add(group)
    await db_session.flush()

    ma = await _mk_monitor(db_session, a.id, "e2e-ma")
    mb = await _mk_monitor(db_session, b.id, "e2e-mb")
    mt = await _mk_monitor(db_session, owner.id, "e2e-mt", team_id=team.id)
    mg = await _mk_monitor(db_session, owner.id, "e2e-mg", group_id=group.id)

    manager = ConnectionManager()
    sock_a = _fake_ws()
    sock_su = _fake_ws()
    sock_c = _fake_ws()
    sock_pub = _fake_ws()
    for sock, ip in ((sock_a, "1"), (sock_su, "2"), (sock_c, "3"), (sock_pub, "4")):
        await manager.connect(sock, client_ip=ip)
    await manager.authorize(sock_a, "dashboard", await _compute_dashboard_scope(db_session, a))
    await manager.authorize(sock_su, "dashboard", await _compute_dashboard_scope(db_session, su))
    await manager.authorize(sock_c, "dashboard", await _compute_dashboard_scope(db_session, member))
    await manager.authorize(sock_pub, "public", await _compute_public_scope(db_session, group.id))

    all_socks = (sock_a, sock_su, sock_c, sock_pub)

    def _reset() -> None:
        for sock in all_socks:
            sock.send_text.reset_mock()

    # Incident on B's monitor → only the superadmin sees it (cross-tenant leak fixed).
    await manager.broadcast({"type": "incident_opened", "monitor_id": str(mb.id)})
    sock_su.send_text.assert_awaited_once()
    sock_a.send_text.assert_not_called()
    sock_c.send_text.assert_not_called()
    sock_pub.send_text.assert_not_called()

    _reset()
    # Incident on A's monitor → A + superadmin.
    await manager.broadcast({"type": "incident_opened", "monitor_id": str(ma.id)})
    sock_a.send_text.assert_awaited_once()
    sock_su.send_text.assert_awaited_once()
    sock_c.send_text.assert_not_called()
    sock_pub.send_text.assert_not_called()

    _reset()
    # Incident on the team monitor → the team member + superadmin.
    await manager.broadcast({"type": "incident_opened", "monitor_id": str(mt.id)})
    sock_c.send_text.assert_awaited_once()
    sock_su.send_text.assert_awaited_once()
    sock_a.send_text.assert_not_called()
    sock_pub.send_text.assert_not_called()

    _reset()
    # Incident on the public group's monitor → the public socket + superadmin.
    await manager.broadcast({"type": "incident_opened", "monitor_id": str(mg.id)})
    sock_pub.send_text.assert_awaited_once()
    sock_su.send_text.assert_awaited_once()
    sock_a.send_text.assert_not_called()
    sock_c.send_text.assert_not_called()
