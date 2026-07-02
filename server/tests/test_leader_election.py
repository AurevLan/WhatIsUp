"""Tests for the Redis-backed leader election used by background loops.

Covers: acquisition, exclusivity between two simulated replicas, atomic renewal,
loss detection, automatic takeover after the lease expires, clean release, and
the degraded fail-open path when Redis is unreachable.
"""

from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio
from fakeredis.aioredis import FakeRedis
from redis.exceptions import ConnectionError as RedisConnectionError

from whatisup.core.leader import LeaderLock, run_leader_loop


@pytest_asyncio.fixture
async def rds():
    r = FakeRedis(decode_responses=True)
    yield r
    await r.aclose()


class _DownRedis:
    """Stand-in that behaves as if Redis is unreachable."""

    async def set(self, *_args, **_kwargs):
        raise RedisConnectionError("redis down")

    def pipeline(self, *_args, **_kwargs):
        raise RedisConnectionError("redis down")


# ── acquisition & exclusivity ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_acquire_sets_key_and_becomes_leader(rds):
    lock = LeaderLock("t_acquire", ttl=5, renew_interval=1, redis=rds)
    assert await lock.try_acquire() is True
    assert lock.is_leader is True
    assert await rds.get("whatisup:leader:t_acquire") == lock.token
    await lock.release()


@pytest.mark.asyncio
async def test_two_instances_only_one_leader(rds):
    """Two replicas contend for the same task — exactly one wins."""
    a = LeaderLock("t_excl", ttl=5, renew_interval=1, redis=rds)
    b = LeaderLock("t_excl", ttl=5, renew_interval=1, redis=rds)

    got_a = await a.try_acquire()
    got_b = await b.try_acquire()

    assert got_a is True
    assert got_b is False
    assert a.is_leader is True
    assert b.is_leader is False
    # The stored token belongs to the winner only.
    assert await rds.get("whatisup:leader:t_excl") == a.token

    await a.release()
    await b.release()


@pytest.mark.asyncio
async def test_acquire_is_idempotent_while_leading(rds):
    lock = LeaderLock("t_idem", ttl=5, renew_interval=1, redis=rds)
    assert await lock.try_acquire() is True
    # Second call must not spawn a second renewer nor lose leadership.
    renewer = lock._renewer
    assert await lock.try_acquire() is True
    assert lock._renewer is renewer
    await lock.release()


# ── renewal ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_renew_extends_only_own_lease(rds):
    owner = LeaderLock("t_renew", ttl=5, renew_interval=1, redis=rds)
    assert await owner.try_acquire() is True

    # Owner can renew.
    assert await owner._renew() is True
    ttl_ms = await rds.pttl("whatisup:leader:t_renew")
    assert ttl_ms > 0

    # A different replica (different token) cannot renew a lock it doesn't hold.
    intruder = LeaderLock("t_renew", ttl=5, renew_interval=1, redis=rds)
    assert await intruder._renew() is False

    await owner.release()


@pytest.mark.asyncio
async def test_renewer_detects_loss(rds):
    """If the key is taken over by another token, the renewer drops leadership."""
    lock = LeaderLock("t_loss", ttl=1, renew_interval=0.05, redis=rds)
    assert await lock.try_acquire() is True
    assert lock.is_leader is True

    # Simulate a foreign takeover (e.g. after our lease had expired).
    await rds.set("whatisup:leader:t_loss", "someone-else")

    # The renewer should notice within a couple of renew intervals.
    for _ in range(40):
        if not lock.is_leader:
            break
        await asyncio.sleep(0.02)
    assert lock.is_leader is False

    await lock.release()


# ── release ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_release_deletes_only_owned_key(rds):
    lock = LeaderLock("t_rel", ttl=5, renew_interval=1, redis=rds)
    await lock.try_acquire()
    await lock.release()
    assert await rds.get("whatisup:leader:t_rel") is None
    assert lock.is_leader is False


@pytest.mark.asyncio
async def test_release_leaves_foreign_key_untouched(rds):
    lock = LeaderLock("t_rel2", ttl=5, renew_interval=1, redis=rds)
    await lock.try_acquire()
    # Someone else now owns the key; our release must not delete it.
    await rds.set("whatisup:leader:t_rel2", "foreign")
    await lock.release()
    assert await rds.get("whatisup:leader:t_rel2") == "foreign"


# ── degraded mode (Redis unreachable) ────────────────────────────────────────


@pytest.mark.asyncio
async def test_degraded_fail_open_on_acquire():
    lock = LeaderLock("t_degraded", ttl=5, renew_interval=1, redis=_DownRedis())
    # Redis is down → fail open so the task still runs on a single replica.
    assert await lock.try_acquire() is True
    assert lock.is_leader is True
    assert lock.degraded is True
    # Renew also fails open rather than dropping leadership.
    assert await lock._renew() is True
    await lock.release()


# ── run_leader_loop integration ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_leader_loop_single_executor(rds):
    """Two loops for the same task → only the leader's work runs."""
    log: list[str] = []

    def make_work(name):
        async def work():
            log.append(name)

        return work

    t1 = asyncio.create_task(
        run_leader_loop(
            "t_loop", make_work("a"), interval=0.02, ttl=1, renew_interval=0.05, redis=rds
        )
    )
    t2 = asyncio.create_task(
        run_leader_loop(
            "t_loop", make_work("b"), interval=0.02, ttl=1, renew_interval=0.05, redis=rds
        )
    )

    await asyncio.sleep(0.25)
    for t in (t1, t2):
        t.cancel()
    for t in (t1, t2):
        with pytest.raises(asyncio.CancelledError):
            await t

    assert log, "leader should have executed at least once"
    assert set(log) == {log[0]}, f"only one replica may execute, saw {set(log)}"


@pytest.mark.asyncio
async def test_run_leader_loop_takeover_after_expiry(rds):
    """A waiting replica takes over once the current lease disappears."""
    # A foreign leader currently holds the lock.
    await rds.set("whatisup:leader:t_take", "foreign", px=10_000)
    log: list[int] = []

    async def work():
        log.append(1)

    task = asyncio.create_task(
        run_leader_loop("t_take", work, interval=0.02, ttl=1, renew_interval=0.05, redis=rds)
    )

    await asyncio.sleep(0.12)
    assert log == [], "must not run while another replica holds the lock"

    # The foreign lease expires / leader dies → key gone.
    await rds.delete("whatisup:leader:t_take")

    await asyncio.sleep(0.15)
    assert len(log) >= 1, "should take over once the lock is free"
    assert await rds.get("whatisup:leader:t_take") is not None

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    # Clean release on shutdown.
    assert await rds.get("whatisup:leader:t_take") is None


@pytest.mark.asyncio
async def test_run_leader_loop_releases_on_cancel(rds):
    started = asyncio.Event()

    async def work():
        started.set()

    task = asyncio.create_task(
        run_leader_loop("t_cancel", work, interval=0.02, ttl=1, renew_interval=0.05, redis=rds)
    )
    await asyncio.wait_for(started.wait(), timeout=1)
    assert await rds.get("whatisup:leader:t_cancel") is not None

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert await rds.get("whatisup:leader:t_cancel") is None
