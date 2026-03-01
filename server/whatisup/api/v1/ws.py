"""WebSocket endpoint for real-time dashboard updates."""

import asyncio
import json

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from jwt.exceptions import InvalidTokenError

from whatisup.core.redis import get_redis
from whatisup.core.security import decode_token

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["websocket"])

REDIS_CHANNEL = "whatisup:events"


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: list[WebSocket] = []
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections.append(websocket)

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections.discard(websocket) if hasattr(self._connections, "discard") else None
            if websocket in self._connections:
                self._connections.remove(websocket)

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
async def websocket_dashboard(websocket: WebSocket, token: str) -> None:
    """Authenticated real-time dashboard WebSocket."""
    await websocket.accept()
    try:
        decode_token(token, "access")
    except InvalidTokenError:
        await websocket.close(code=4001, reason="Unauthorized")
        return

    async with manager._lock:
        manager._connections.append(websocket)
    try:
        while True:
            # Keep-alive: receive pings, ignore content
            await websocket.receive_text()
    except WebSocketDisconnect:
        await manager.disconnect(websocket)


@router.websocket("/ws/public/{slug}")
async def websocket_public(websocket: WebSocket, slug: str) -> None:
    """Unauthenticated real-time WebSocket for public status pages."""
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await manager.disconnect(websocket)
