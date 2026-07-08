"""Per-account login lockout backed by Redis (SA2).

Counts failed password attempts per *submitted* identifier (normalized
email), so unknown accounts behave exactly like real ones. Once the
threshold is reached within the window, the account is locked for a fixed
duration; during the lockout the login endpoint answers exactly like a
wrong password (anti-enumeration — the lockout must never be observable).

Fail-open by design: if Redis is unavailable, lockout checks are skipped —
the per-IP slowapi rate limit on /login remains the backstop (same policy
as the other Redis-backed guards in the project).
"""

from __future__ import annotations

import hashlib

import structlog
from redis.exceptions import RedisError

from whatisup.core.redis import get_redis

logger = structlog.get_logger(__name__)

# 10 failed attempts within a 15-minute window → locked for 15 minutes.
LOCKOUT_THRESHOLD = 10
LOCKOUT_WINDOW_SECONDS = 15 * 60
LOCKOUT_DURATION_SECONDS = 15 * 60


def _digest(identifier: str) -> str:
    normalized = identifier.strip().lower()
    # SHA-256 as a key index only — keeps raw identifiers (PII) out of Redis
    return hashlib.sha256(normalized.encode(), usedforsecurity=False).hexdigest()[:32]


def fail_key(identifier: str) -> str:
    return f"whatisup:lockout:fail:{_digest(identifier)}"


def lock_key(identifier: str) -> str:
    return f"whatisup:lockout:lock:{_digest(identifier)}"


async def is_locked(identifier: str) -> bool:
    """True if the identifier is currently locked out. Fail-open on Redis errors."""
    try:
        return bool(await get_redis().exists(lock_key(identifier)))
    except (RedisError, OSError) as exc:
        logger.warning("lockout_redis_unavailable", op="is_locked", error=str(exc))
        return False


async def register_failure(identifier: str) -> bool:
    """Record one failed password attempt.

    Returns True only when this attempt *triggers* the lockout, so the caller
    can emit a single audit entry. Fail-open on Redis errors.
    """
    try:
        redis = get_redis()
        key = fail_key(identifier)
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, LOCKOUT_WINDOW_SECONDS)
        if count >= LOCKOUT_THRESHOLD:
            # NX → only the attempt crossing the threshold reports the trigger;
            # an already-active lock is never extended.
            created = await redis.set(
                lock_key(identifier), "1", ex=LOCKOUT_DURATION_SECONDS, nx=True
            )
            return bool(created)
        return False
    except (RedisError, OSError) as exc:
        logger.warning("lockout_redis_unavailable", op="register_failure", error=str(exc))
        return False


async def reset_failures(identifier: str) -> None:
    """Clear the failure counter after a successful password verification."""
    try:
        await get_redis().delete(fail_key(identifier), lock_key(identifier))
    except (RedisError, OSError) as exc:
        logger.warning("lockout_redis_unavailable", op="reset", error=str(exc))
