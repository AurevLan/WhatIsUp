"""Redis async client singleton + fail-open helpers for cache-only paths."""

from __future__ import annotations

import asyncio

import redis.asyncio as aioredis
import structlog
from redis.exceptions import RedisError

from whatisup.core.config import get_settings

logger = structlog.get_logger(__name__)

_redis: aioredis.Redis | None = None

# Redis client errors + raw socket errors + timeouts. Anything else (bugs,
# cancellation) must keep propagating.
_FAIL_OPEN_ERRORS = (RedisError, OSError, asyncio.TimeoutError)


def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        settings = get_settings()
        _redis = aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
    return _redis


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None


# ── Fail-open helpers ────────────────────────────────────────────────────────
# For paths where Redis is a cache/accelerator, never the source of truth
# (e.g. API-key auth: the fallback is a bcrypt check against the DB). A Redis
# outage degrades to a cache miss instead of a 500. Do NOT use these where
# Redis holds authoritative state (rate limiting counters, digest queues).


async def redis_get_safe(key: str) -> str | bytes | None:
    """GET that treats a Redis outage as a cache miss."""
    try:
        return await get_redis().get(key)
    except _FAIL_OPEN_ERRORS as exc:
        logger.warning("redis_unavailable_fail_open", op="get", error=type(exc).__name__)
        return None


async def redis_setex_safe(key: str, ttl_seconds: int, value: str) -> bool:
    """SETEX that silently skips the cache write on a Redis outage."""
    try:
        await get_redis().setex(key, ttl_seconds, value)
        return True
    except _FAIL_OPEN_ERRORS as exc:
        logger.warning("redis_unavailable_fail_open", op="setex", error=type(exc).__name__)
        return False


async def redis_delete_safe(*keys: str) -> bool:
    """DEL that tolerates a Redis outage.

    Safe for auth-cache eviction: stale entries are defused by the hash
    fingerprint embedded in every cache value (fast path re-validates it
    against the live DB row on each hit), and they expire with the TTL anyway.
    """
    try:
        if keys:
            await get_redis().delete(*keys)
        return True
    except _FAIL_OPEN_ERRORS as exc:
        logger.warning("redis_unavailable_fail_open", op="delete", error=type(exc).__name__)
        return False
