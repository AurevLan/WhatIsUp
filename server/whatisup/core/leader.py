"""Distributed leader election for singleton background loops.

WhatIsUp runs a handful of periodic background loops from the FastAPI lifespan
(heartbeat watchdog, retention purge, renotify, digest flusher, SLA reports,
network-verdict recompute, ASN refresh). When the API is scaled to N replicas
each of those loops would otherwise run N times — duplicating incidents,
alerts and purges.

This module provides a Redis-backed leader lock so that, for each named task,
only one replica does the work at a time. It uses ``SET key token NX PX`` for
acquisition and an atomic compare-and-set (WATCH/MULTI transaction) for renewal
and release, so a replica never touches a lock owned by another. A short TTL
with periodic renewal means that if the current leader dies, another replica
takes over automatically once the key expires.

Degraded mode (Redis unreachable): acquisition/renewal *fail open* — the caller
is treated as leader and the loop runs anyway, with a throttled warning log.
Rationale: the overwhelmingly common deployment is a single replica, where
Redis being down must not silently stop retention/heartbeat/alerting. The
accepted trade-off is that during a Redis outage a multi-replica deployment may
run a loop more than once; that is strictly better than dropping the work, and
self-heals on the next renewal once Redis returns (the stale local leadership is
detected and dropped, then re-elected cleanly).
"""

from __future__ import annotations

import asyncio
import uuid

import structlog
from redis.exceptions import RedisError, WatchError

from whatisup.core.redis import get_redis

logger = structlog.get_logger(__name__)

# Key namespace shared with the rest of the app (rate-limit, digests, …).
_KEY_PREFIX = "whatisup:leader:"

# Short lease so a dead leader is reclaimed quickly, with renewal well within it.
DEFAULT_TTL_SECONDS = 30.0
DEFAULT_RENEW_SECONDS = 10.0


class LeaderLock:
    """A renewable, single-owner distributed lock for one named task.

    Typical use is via :func:`run_leader_loop`, but the primitive is exposed so
    bespoke schedules (e.g. the cron-like retention job) can gate their work:

    >>> lock = LeaderLock("my_task")
    >>> if await lock.try_acquire():
    ...     await do_work()
    >>> await lock.release()  # on shutdown
    """

    def __init__(
        self,
        task_name: str,
        *,
        ttl: float = DEFAULT_TTL_SECONDS,
        renew_interval: float = DEFAULT_RENEW_SECONDS,
        redis=None,
    ) -> None:
        if renew_interval >= ttl:
            raise ValueError("renew_interval must be shorter than ttl")
        self.task_name = task_name
        self.key = f"{_KEY_PREFIX}{task_name}"
        # Unique per lock instance (i.e. per replica) — the fencing token proving
        # ownership so we only ever renew/release a lock we actually hold.
        self.token = uuid.uuid4().hex
        self.ttl = ttl
        self.renew_interval = renew_interval
        self._redis = redis
        self._is_leader = False
        self._degraded = False
        self._renewer: asyncio.Task | None = None

    @property
    def redis(self):
        return self._redis if self._redis is not None else get_redis()

    @property
    def is_leader(self) -> bool:
        """Local view of leadership.

        True while this replica holds the lock (renewer alive) or while running
        in degraded fail-open mode. Set to False by the renewer the moment it
        detects the lock was lost.
        """
        return self._is_leader

    @property
    def degraded(self) -> bool:
        """True when the last Redis interaction failed and we failed open."""
        return self._degraded

    async def try_acquire(self) -> bool:
        """Attempt to become leader. Idempotent while already leading.

        Returns True if this replica may run the task (either it holds the lock,
        or Redis is unreachable and we fail open). Starts the background renewer
        on a fresh acquisition.
        """
        # Already leading with a live renewer — nothing to do.
        if self._is_leader and self._renewer is not None and not self._renewer.done():
            return True

        # Renewer finished (lost the lock, or first call) — reset local state.
        if self._renewer is not None and self._renewer.done():
            self._is_leader = False
            self._renewer = None

        try:
            acquired = await self.redis.set(self.key, self.token, nx=True, px=int(self.ttl * 1000))
            self._degraded = False
        except RedisError as exc:
            self._on_redis_down("acquire", exc)
            self._is_leader = True
            self._start_renewer()
            return True

        if not acquired:
            # NX refused, but the live key may be our *own* lease — e.g. the
            # renewer crashed leaving our token behind. Confirm and extend
            # atomically (_renew is WATCH-guarded, so a concurrent takeover
            # between GET and the extension is detected, not clobbered).
            try:
                current = await self.redis.get(self.key)
            except RedisError:
                current = None
            if current == self.token:
                acquired = await self._renew()

        if acquired:
            self._is_leader = True
            self._start_renewer()
            return True

        self._is_leader = False
        return False

    def _start_renewer(self) -> None:
        if self._renewer is None or self._renewer.done():
            self._renewer = asyncio.create_task(self._renew_loop())

    async def _renew_loop(self) -> None:
        """Keep the lease alive until leadership is lost or the task is cancelled."""
        while True:
            await asyncio.sleep(self.renew_interval)
            held = await self._renew()
            if not held:
                logger.warning("leader_lock_lost", task=self.task_name)
                self._is_leader = False
                return

    async def _renew(self) -> bool:
        """Atomically extend the lease iff we still own it.

        Uses an optimistic WATCH/MULTI transaction (fakeredis and real Redis both
        support it, unlike server-side Lua). Fails open on Redis *outages* only;
        a WATCH invalidation means the key changed hands and is a legitimate
        loss of leadership, never a reason to fail open.
        """
        try:
            async with self.redis.pipeline(transaction=True) as pipe:
                await pipe.watch(self.key)
                current = await pipe.get(self.key)
                if current != self.token:
                    await pipe.reset()
                    self._degraded = False
                    return False
                pipe.multi()
                pipe.pexpire(self.key, int(self.ttl * 1000))
                await pipe.execute()
                self._degraded = False
                return True
        except WatchError:
            # The key expired or was taken over between GET and EXEC — Redis is
            # healthy, we simply lost the lock. Must NOT be treated as an
            # outage (WatchError subclasses RedisError): failing open here
            # would keep two leaders running.
            self._degraded = False
            return False
        except RedisError as exc:
            self._on_redis_down("renew", exc)
            return True

    async def release(self) -> None:
        """Stop renewing and drop the lock iff we still own it (best effort)."""
        if self._renewer is not None:
            self._renewer.cancel()
            try:
                await self._renewer
            except asyncio.CancelledError:
                pass
            self._renewer = None
        was_leader = self._is_leader
        self._is_leader = False
        if not was_leader:
            return
        try:
            async with self.redis.pipeline(transaction=True) as pipe:
                await pipe.watch(self.key)
                current = await pipe.get(self.key)
                if current != self.token:
                    await pipe.reset()
                    return
                pipe.multi()
                pipe.delete(self.key)
                await pipe.execute()
        except WatchError:
            # Key changed hands between GET and EXEC — it is no longer ours,
            # so there is nothing to delete. Not an outage, stay silent.
            return
        except RedisError as exc:
            # TTL will reclaim the key; nothing else to do.
            logger.warning(
                "leader_lock_release_failed",
                task=self.task_name,
                error_type=type(exc).__name__,
            )

    def _on_redis_down(self, op: str, exc: RedisError) -> None:
        if not self._degraded:
            logger.warning(
                "leader_lock_degraded",
                task=self.task_name,
                op=op,
                error_type=type(exc).__name__,
                detail="Redis unreachable — failing open, task runs on this replica",
            )
        self._degraded = True


async def run_leader_loop(
    task_name: str,
    work,
    *,
    interval,
    initial_delay: float = 0.0,
    ttl: float = DEFAULT_TTL_SECONDS,
    renew_interval: float = DEFAULT_RENEW_SECONDS,
    redis=None,
) -> None:
    """Run ``work`` on a fixed cadence, but only on the elected leader replica.

    Structure mirrors the original inline loops (run-then-sleep) so task
    semantics are unchanged: metrics label, error handling and cadence are
    preserved. On every iteration leadership is (re)checked before doing work,
    and the lock is released cleanly on cancellation (shutdown).

    Caveat: leadership is only checked *before* each iteration — losing the
    lock mid-iteration does not cancel the in-flight ``work()``, so one
    iteration may briefly overlap with the new leader (no DB-side fencing).

    :param work: zero-arg coroutine function performing one iteration.
    :param interval: seconds between iterations — a float or a zero-arg callable
        returning a float (evaluated each iteration, for cron-like schedules).
    :param initial_delay: seconds to wait before the first iteration.
    """
    from whatisup.core.metrics import track_background_task

    lock = LeaderLock(task_name, ttl=ttl, renew_interval=renew_interval, redis=redis)
    try:
        if initial_delay:
            await asyncio.sleep(initial_delay)
        while True:
            try:
                await lock.try_acquire()
            except Exception as exc:
                # try_acquire handles RedisError itself (fail open); anything
                # else is unexpected — log and keep the loop alive rather than
                # letting the background task die silently.
                logger.error(
                    "leader_acquire_error",
                    task=task_name,
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
            if lock.is_leader:
                try:
                    async with track_background_task(task_name):
                        await work()
                except Exception as exc:
                    logger.error(
                        f"{task_name}_error",
                        error_type=type(exc).__name__,
                        error=str(exc),
                    )
            sleep_for = interval() if callable(interval) else interval
            await asyncio.sleep(sleep_for)
    finally:
        # Best effort — release() swallows WatchError/RedisError itself, but a
        # shutdown must never be broken by an unexpected release failure.
        try:
            await lock.release()
        except Exception as exc:
            logger.warning(
                "leader_release_error",
                task=task_name,
                error_type=type(exc).__name__,
            )
