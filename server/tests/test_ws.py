"""Tests for the WebSocket dashboard/public endpoints and ConnectionManager.

The dashboard auth protocol (auth-by-message, never ?token= in the URL) is a
hard security rule — these tests pin it.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.websockets import WebSocketDisconnect

from whatisup.api.v1.ws import MAX_CONNECTIONS_PER_IP, ConnectionManager
from whatisup.core.database import get_db
from whatisup.core.security import create_access_token, create_refresh_token
from whatisup.main import app

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

    await manager.broadcast({"type": "check_result"})

    alive.send_text.assert_awaited_once_with(json.dumps({"type": "check_result"}))
    assert dead not in manager._connections
    assert alive in manager._connections


# ── Dashboard WS auth protocol ────────────────────────────────────────────────


@pytest.fixture
def ws_client(db_session: AsyncSession, fake_redis) -> TestClient:
    """Sync TestClient (httpx ASGITransport has no WebSocket support)."""
    import whatisup.core.redis as redis_module

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    redis_module._redis = fake_redis
    yield TestClient(app)
    app.dependency_overrides.clear()
    redis_module._redis = None


def test_ws_dashboard_valid_auth_keeps_connection(ws_client: TestClient) -> None:
    token = create_access_token("user-1")
    with ws_client.websocket_connect("/ws/dashboard") as ws:
        ws.send_text(json.dumps({"type": "auth", "token": token}))
        # Connection stays open: a ping frame is accepted without error
        ws.send_text("ping")


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


def test_ws_public_unknown_slug_closed(ws_client: TestClient) -> None:
    # The route closes before accepting → the handshake itself fails with 4004
    with pytest.raises(WebSocketDisconnect) as exc_info:  # noqa: SIM117
        with ws_client.websocket_connect("/ws/public/unknown-slug"):
            pass
    assert exc_info.value.code == 4004
