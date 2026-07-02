"""WebSocket endpoint for real-time dashboard updates.

Tenant scoping (finding audit M1)
---------------------------------
Every connection carries a **scope** decided at authentication time:

* ``/ws/dashboard`` — the set of monitor ids the authenticated user may see
  (owner + team membership, via ``build_access_filter``). Superadmins get the
  ``SUPERADMIN_SCOPE`` sentinel (``None``) meaning "everything".
* ``/ws/public/{slug}`` — only the monitor ids belonging to the group behind
  the slug. Anonymous visitors therefore never receive incidents/topology of
  other tenants.

``broadcast`` filters every event by its ``monitor_id`` against the connection
scope. The check is an in-memory set lookup — no DB hit on the hot path.

Scope freshness: the scope is a snapshot taken at connect and lazily refreshed
at most once per ``SCOPE_REFRESH_SECONDS`` when a keep-alive frame arrives
(the frontend pings every 30 s). A refresh failure keeps the previous scope
(fail-closed: a stale scope never *widens* silently beyond what it already
allowed). A brand-new / newly-shared monitor thus becomes visible within one
refresh window or on reconnect.

Events without a ``monitor_id`` (none exist today; reserved for future global
announcements / probe-fleet events) are delivered to authenticated dashboard
sockets only — never to anonymous public status-page sockets.
"""

import asyncio
import json
import time
import uuid

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from jwt.exceptions import InvalidTokenError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.api.deps import build_access_filter, get_user_team_ids
from whatisup.core.database import get_session_factory
from whatisup.core.redis import get_redis
from whatisup.core.security import decode_token
from whatisup.models.monitor import Monitor, MonitorGroup
from whatisup.models.user import User

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["websocket"])

REDIS_CHANNEL = "whatisup:events"
MAX_CONNECTIONS_PER_IP = 10

# Lazy scope refresh cadence (seconds). The frontend keep-alive pings every 30 s,
# so a live dashboard scope is re-evaluated roughly this often without any extra
# traffic. Kept off the broadcast hot path entirely.
SCOPE_REFRESH_SECONDS = 60

# Scope sentinels ─────────────────────────────────────────────────────────────
# A connection registered but not yet authenticated → receives nothing.
UNAUTHED = object()
# An authenticated superadmin dashboard → receives every event.
SUPERADMIN_SCOPE = None


class ConnectionManager:
    def __init__(self) -> None:
        # ws → {"kind": "dashboard"|"public"|None, "scope": UNAUTHED|None|set[str]}
        self._connections: dict[WebSocket, dict] = {}
        self._ip_counts: dict[str, int] = {}
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, client_ip: str | None = None) -> bool:
        """Accept a WebSocket connection. Returns False if per-IP limit exceeded.

        The connection starts ``UNAUTHED`` and receives **no** broadcast until
        :meth:`authorize` attaches a scope.
        """
        if client_ip:
            async with self._lock:
                if self._ip_counts.get(client_ip, 0) >= MAX_CONNECTIONS_PER_IP:
                    return False
                self._ip_counts[client_ip] = self._ip_counts.get(client_ip, 0) + 1
        await websocket.accept()
        async with self._lock:
            self._connections[websocket] = {"kind": None, "scope": UNAUTHED}
            if client_ip:
                websocket._client_ip = client_ip  # store for cleanup
        return True

    async def authorize(self, websocket: WebSocket, kind: str, scope: set[str] | None) -> None:
        """Attach a tenant scope to a connection once authenticated.

        ``scope`` is ``SUPERADMIN_SCOPE`` (None) for "everything", otherwise a
        set of monitor-id strings the connection is allowed to receive.
        """
        async with self._lock:
            conn = self._connections.get(websocket)
            if conn is not None:
                conn["kind"] = kind
                conn["scope"] = scope

    async def set_scope(self, websocket: WebSocket, scope: set[str] | None) -> None:
        """Refresh the scope of an already-authenticated connection.

        No-op if the connection is gone or still ``UNAUTHED`` (never promote an
        unauthenticated socket via a refresh path).
        """
        async with self._lock:
            conn = self._connections.get(websocket)
            if conn is not None and conn["scope"] is not UNAUTHED:
                conn["scope"] = scope

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections.pop(websocket, None)
            # Decrement IP counter
            client_ip = getattr(websocket, "_client_ip", None)
            if client_ip and client_ip in self._ip_counts:
                self._ip_counts[client_ip] = max(0, self._ip_counts[client_ip] - 1)
                if self._ip_counts[client_ip] == 0:
                    del self._ip_counts[client_ip]

    @staticmethod
    def _should_deliver(conn: dict, monitor_id: str | None) -> bool:
        """Decide whether *conn* is allowed to receive an event.

        Pure in-memory set lookup — safe to call per message on the hot path.
        """
        scope = conn["scope"]
        if scope is UNAUTHED:
            return False
        if monitor_id is None:
            # Global / no-monitor events → authenticated dashboard sockets only,
            # never anonymous public status-page sockets.
            return conn["kind"] == "dashboard"
        if scope is SUPERADMIN_SCOPE:
            return True
        return monitor_id in scope

    async def broadcast(self, event: dict) -> None:
        message = json.dumps(event)
        monitor_id = event.get("monitor_id")
        dead: list[WebSocket] = []
        async with self._lock:
            targets = list(self._connections.items())
        for ws, conn in targets:
            if not self._should_deliver(conn, monitor_id):
                continue
            try:
                await ws.send_text(message)
            except Exception as exc:
                logger.debug("ws_send_failed", error=str(exc))
                dead.append(ws)
        for ws in dead:
            await self.disconnect(ws)


manager = ConnectionManager()


def _scope_session():
    """Short-lived DB session context manager used for scope computation.

    A WebSocket must never hold a pooled DB connection for its whole lifetime,
    so scope is fetched via a fresh session that is opened, queried, and closed
    immediately (at connect and on lazy refresh). Indirected behind this helper
    so tests can inject the in-memory test session.
    """
    return get_session_factory()()


async def _compute_dashboard_scope(db: AsyncSession, user: User) -> set[str] | None:
    """Set of monitor ids the user may receive events for.

    Returns ``SUPERADMIN_SCOPE`` (None) for superadmins (everything). Reuses the
    exact ownership + team authorization logic used by the REST list endpoints
    (``build_access_filter`` / ``get_user_team_ids``) so the WS surface can never
    be broader than the HTTP one.
    """
    if user.is_superadmin:
        return SUPERADMIN_SCOPE
    team_ids = await get_user_team_ids(user, db)
    rows = (
        (await db.execute(select(Monitor.id).where(build_access_filter(Monitor, user, team_ids))))
        .scalars()
        .all()
    )
    return {str(mid) for mid in rows}


async def _compute_public_scope(db: AsyncSession, group_id: uuid.UUID) -> set[str]:
    """Set of monitor ids belonging to the public group behind a slug."""
    rows = (
        (await db.execute(select(Monitor.id).where(Monitor.group_id == group_id))).scalars().all()
    )
    return {str(mid) for mid in rows}


async def _serve_keepalive(websocket: WebSocket, recompute) -> None:
    """Keep-alive loop with lazy scope refresh.

    Blocks on incoming frames (client pings); every ``SCOPE_REFRESH_SECONDS`` it
    recomputes the scope via *recompute* (an async callable returning the new
    scope). A refresh failure is swallowed — the previous scope stands.
    """
    last_refresh = time.monotonic()
    while True:
        await websocket.receive_text()
        now = time.monotonic()
        if now - last_refresh >= SCOPE_REFRESH_SECONDS:
            last_refresh = now
            try:
                await manager.set_scope(websocket, await recompute())
            except Exception as exc:
                logger.warning("ws_scope_refresh_failed", error=str(exc))


async def _redis_subscriber() -> None:
    """Background task: subscribe to Redis and broadcast to all WS clients."""
    backoff = 2
    while True:
        pubsub = None
        try:
            redis = get_redis()
            pubsub = redis.pubsub()
            await pubsub.subscribe(REDIS_CHANNEL)
            logger.info("ws_redis_subscriber_started", channel=REDIS_CHANNEL)
            backoff = 2
            async for message in pubsub.listen():
                if message["type"] == "message":
                    try:
                        event = json.loads(message["data"])
                        await manager.broadcast(event)
                    except Exception as exc:
                        logger.error("ws_broadcast_error", error=str(exc))
        except Exception as exc:
            logger.error("ws_redis_subscriber_crashed", error=str(exc))
            # Exponential backoff: 2, 4, 8, 16, max 60s
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)
        finally:
            # aclose() (not unsubscribe) returns the connection to the pool —
            # without it every crash leaks one connection until the pool is dry
            # and ALL Redis calls fail (login included).
            if pubsub is not None:
                try:
                    await pubsub.aclose()
                except Exception:
                    pass


@router.websocket("/ws/dashboard")
async def websocket_dashboard(websocket: WebSocket) -> None:
    """Authenticated real-time dashboard WebSocket.

    Auth protocol: after connect, client must send a JSON frame
    {"type": "auth", "token": "<access_jwt>"} within 5 seconds.
    JWT is validated server-side; failure closes with code 4001.
    This avoids leaking the token in server access logs (ANSSI recommendation).

    On success the connection is scoped to the monitors the user may see; the
    user must still exist and be active (a revoked/deleted user's stale JWT is
    rejected). Per-IP connection limit is enforced via the ConnectionManager.
    """
    client_ip = websocket.client.host if websocket.client else None
    accepted = await manager.connect(websocket, client_ip=client_ip)
    if not accepted:
        await websocket.close(code=4029, reason="Too many connections from this IP")
        return

    try:
        auth_text = await asyncio.wait_for(websocket.receive_text(), timeout=5.0)
        auth_data = json.loads(auth_text)
        if auth_data.get("type") != "auth" or not auth_data.get("token"):
            raise ValueError("Expected auth frame")
        payload = decode_token(auth_data["token"], "access")
        user_id = uuid.UUID(payload["sub"])
    except (TimeoutError, json.JSONDecodeError, ValueError, InvalidTokenError, KeyError):
        await manager.disconnect(websocket)
        await websocket.close(code=4001, reason="Unauthorized")
        return

    # Short-lived session: load the user and compute the initial scope, then
    # release the connection before the (indefinite) keep-alive loop.
    try:
        async with _scope_session() as db:
            user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
            if user is None or not user.is_active:
                await manager.disconnect(websocket)
                await websocket.close(code=4001, reason="Unauthorized")
                return
            scope = await _compute_dashboard_scope(db, user)
    except Exception as exc:
        logger.warning("ws_dashboard_scope_error", error=str(exc))
        await manager.disconnect(websocket)
        await websocket.close(code=4001, reason="Unauthorized")
        return

    await manager.authorize(websocket, "dashboard", scope)

    async def _recompute() -> set[str] | None:
        async with _scope_session() as db:
            return await _compute_dashboard_scope(db, user)

    try:
        await _serve_keepalive(websocket, _recompute)
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.warning("ws_dashboard_error", error=str(exc))
    finally:
        await manager.disconnect(websocket)


@router.websocket("/ws/public/{slug}")
async def websocket_public(websocket: WebSocket, slug: str) -> None:
    """Unauthenticated real-time WebSocket for public status pages.

    Validates that the slug corresponds to an existing public group before
    accepting the connection. The connection is scoped to that group's monitors
    only — an anonymous visitor never receives incidents/topology of other
    tenants. Limited to MAX_CONNECTIONS_PER_IP concurrent connections per IP.
    """
    async with _scope_session() as db:
        group = (
            await db.execute(select(MonitorGroup).where(MonitorGroup.public_slug == slug))
        ).scalar_one_or_none()
    if group is None:
        await websocket.close(code=4004, reason="Not found")
        return

    client_ip = websocket.client.host if websocket.client else None
    accepted = await manager.connect(websocket, client_ip=client_ip)
    if not accepted:
        await websocket.close(code=4029, reason="Too many connections from this IP")
        return

    group_id = group.id
    async with _scope_session() as db:
        scope = await _compute_public_scope(db, group_id)
    await manager.authorize(websocket, "public", scope)

    async def _recompute() -> set[str]:
        async with _scope_session() as db:
            return await _compute_public_scope(db, group_id)

    try:
        await _serve_keepalive(websocket, _recompute)
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.warning("ws_public_error", error=str(exc))
    finally:
        await manager.disconnect(websocket)
