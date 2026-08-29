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


async def redis_incr_safe(key: str, *, ttl_seconds: int | None = None) -> int | None:
    """INCR that treats a Redis outage as "unknown" rather than a hard error.

    Returns ``None`` on failure — the caller decides how to fail open (e.g. a
    per-IP WS connection cap must accept the connection rather than reject
    everyone when the counter itself is unavailable; this is an anti-abuse
    guard, not an ingestion quota like ``services/metric_ingest.py``'s, which
    fails *closed* on purpose).

    ``ttl_seconds``, when given, is applied only on the increment that creates
    the key (``INCR`` returning 1) — a process that crashes before its
    matching decrement would otherwise leak the count forever.
    """
    try:
        redis = get_redis()
        value = await redis.incr(key)
        if ttl_seconds is not None and value == 1:
            await redis.expire(key, ttl_seconds)
        return value
    except _FAIL_OPEN_ERRORS as exc:
        logger.warning("redis_unavailable_fail_open", op="incr", error=type(exc).__name__)
        return None


async def redis_decr_safe(key: str) -> None:
    """DECR that tolerates a Redis outage — best effort, never raises.

    Deletes the key once it reaches zero (or below, which should not happen
    in steady state but is defensive against the TTL racing a decrement)
    rather than leaving a stale ``0`` counter around forever.
    """
    try:
        redis = get_redis()
        value = await redis.decr(key)
        if value <= 0:
            await redis.delete(key)
    except _FAIL_OPEN_ERRORS as exc:
        logger.warning("redis_unavailable_fail_open", op="decr", error=type(exc).__name__)
