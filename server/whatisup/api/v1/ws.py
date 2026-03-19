"""WebSocket endpoint for real-time dashboard updates."""

import asyncio
import json

import structlog
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from jwt.exceptions import InvalidTokenError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.core.database import get_db
from whatisup.core.redis import get_redis
from whatisup.core.security import decode_token

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["websocket"])

REDIS_CHANNEL = "whatisup:events"
MAX_CONNECTIONS_PER_IP = 10


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: list[WebSocket] = []
        self._ip_counts: dict[str, int] = {}
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, client_ip: str | None = None) -> bool:
        """Accept a WebSocket connection. Returns False if per-IP limit exceeded."""
        if client_ip:
            async with self._lock:
                if self._ip_counts.get(client_ip, 0) >= MAX_CONNECTIONS_PER_IP:
                    return False
                self._ip_counts[client_ip] = self._ip_counts.get(client_ip, 0) + 1
        await websocket.accept()
        async with self._lock:
            self._connections.append(websocket)
            if client_ip:
                websocket._client_ip = client_ip  # store for cleanup
        return True

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            if websocket in self._connections:
                self._connections.remove(websocket)
            # Decrement IP counter
            client_ip = getattr(websocket, "_client_ip", None)
            if client_ip and client_ip in self._ip_counts:
                self._ip_counts[client_ip] = max(0, self._ip_counts[client_ip] - 1)
                if self._ip_counts[client_ip] == 0:
                    del self._ip_counts[client_ip]

    async def broadcast(self, event: dict) -> None:
        message = json.dumps(event)
        dead: list[WebSocket] = []
        async with self._lock:
            connections = list(self._connections)
        for ws in connections:
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            await self.disconnect(ws)


manager = ConnectionManager()


async def _redis_subscriber() -> None:
    """Background task: subscribe to Redis and broadcast to all WS clients."""
    redis = get_redis()
    pubsub = redis.pubsub()
    await pubsub.subscribe(REDIS_CHANNEL)
    logger.info("ws_redis_subscriber_started", channel=REDIS_CHANNEL)
    try:
        async for message in pubsub.listen():
            if message["type"] == "message":
                try:
                    event = json.loads(message["data"])
                    await manager.broadcast(event)
                except Exception as exc:
                    logger.error("ws_broadcast_error", error=str(exc))
    finally:
        await pubsub.unsubscribe(REDIS_CHANNEL)


@router.websocket("/ws/dashboard")
async def websocket_dashboard(websocket: WebSocket) -> None:
    """Authenticated real-time dashboard WebSocket.

    Auth protocol: after connect, client must send a JSON frame
    {"type": "auth", "token": "<access_jwt>"} within 5 seconds.
    JWT is validated server-side; failure closes with code 4001.
    This avoids leaking the token in server access logs (ANSSI recommendation).

    Per-IP connection limit is enforced via the shared ConnectionManager.
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
        decode_token(auth_data["token"], "access")
    except (TimeoutError, json.JSONDecodeError, ValueError, InvalidTokenError):
        await manager.disconnect(websocket)
        await websocket.close(code=4001, reason="Unauthorized")
        return

    try:
        while True:
            # Keep-alive: receive pings, ignore content
            await websocket.receive_text()
    except WebSocketDisconnect:
        await manager.disconnect(websocket)


@router.websocket("/ws/public/{slug}")
async def websocket_public(
    websocket: WebSocket,
    slug: str,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Unauthenticated real-time WebSocket for public status pages.

    Validates that the slug corresponds to an existing public group before
    accepting the connection. Limited to MAX_CONNECTIONS_PER_IP concurrent
    connections per IP address to prevent abuse.
    """
    from whatisup.models.monitor import MonitorGroup

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
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await manager.disconnect(websocket)
