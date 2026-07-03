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

    async def get(self, *_args, **_kwargs):
        raise RedisConnectionError("redis down")

    def pipeline(self, *_args, **_kwargs):
        raise RedisConnectionError("redis down")


class _WatchBustedPipeline:
    """Wraps a real pipeline; an 'intruder' mutates the watched key just before
    EXEC, so fakeredis raises a genuine ``redis.WatchError``."""

    def __init__(self, base, key, transaction):
        self._pipe = base.pipeline(transaction=transaction)
        self._base = base
        self._key = key

    def __getattr__(self, name):
        return getattr(self._pipe, name)

    async def __aenter__(self):
        await self._pipe.__aenter__()
        return self

    async def __aexit__(self, *exc):
        return await self._pipe.__aexit__(*exc)

    async def execute(self, *args, **kwargs):
        await self._base.set(self._key, "intruder")
        return await self._pipe.execute(*args, **kwargs)


class _WatchBustedRedis:
    """Proxy over FakeRedis whose transactions always lose the WATCH race."""

    def __init__(self, base, key):
        self._base = base
        self._key = key

    def __getattr__(self, name):
        return getattr(self._base, name)

    def pipeline(self, transaction=True):
        return _WatchBustedPipeline(self._base, self._key, transaction)


class _ExplodingRedis:
    """Raises a non-RedisError from set() while ``broken``; delegates otherwise."""

    def __init__(self, base):
        self._base = base
        self.broken = True

    def __getattr__(self, name):
        return getattr(self._base, name)

    async def set(self, *args, **kwargs):
        if self.broken:
            raise ValueError("unexpected bug")
        return await self._base.set(*args, **kwargs)


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


# ── WATCH invalidation (lost race ≠ Redis outage) ────────────────────────────


@pytest.mark.asyncio
async def test_renew_watch_invalidation_means_lost_not_degraded(rds):
    """A WATCH invalidation (key changed between GET and EXEC) is a legitimate
    loss of leadership. Before the fix, ``WatchError`` (a ``RedisError``
    subclass) fell into the fail-open branch and the replica wrongly stayed
    leader alongside the intruder — this test pins the classification.
    """
    lock = LeaderLock("t_watch", ttl=5, renew_interval=4, redis=rds)
    assert await lock.try_acquire() is True

    # From now on every transaction loses the WATCH race to an intruder.
    lock._redis = _WatchBustedRedis(rds, lock.key)

    assert await lock._renew() is False, "WATCH invalidation must mean lost leadership"
    # Redis is healthy — this must not be flagged as a degraded outage.
    assert lock.degraded is False

    await lock.release()


@pytest.mark.asyncio
async def test_release_watch_invalidation_is_silent_and_safe(rds):
    """A WATCH invalidation during release must not raise, and must leave the
    intruder's key untouched."""
    lock = LeaderLock("t_watch_rel", ttl=5, renew_interval=4, redis=rds)
    assert await lock.try_acquire() is True

    lock._redis = _WatchBustedRedis(rds, lock.key)
    await lock.release()  # must not raise despite the failed transaction

    assert lock.is_leader is False
    assert await rds.get(lock.key) == "intruder"


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


# ── acquisition robustness ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_try_acquire_reclaims_own_leftover_key(rds):
    """If our own token is still alive in Redis (e.g. the renewer crashed
    without releasing), try_acquire must reclaim the lease instead of treating
    it as foreign and losing leadership forever."""
    lock = LeaderLock("t_reclaim", ttl=5, renew_interval=1, redis=rds)
    # Simulate the leftover lease from a previous life of this replica.
    await rds.set(lock.key, lock.token, px=2000)

    assert await lock.try_acquire() is True
    assert lock.is_leader is True
    # The lease was atomically extended back to the full TTL.
    assert await rds.pttl(lock.key) > 2000

    await lock.release()
    assert await rds.get(lock.key) is None


# ── run_leader_loop integration ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_leader_loop_survives_unexpected_acquire_error(rds):
    """A non-RedisError escaping try_acquire must not kill the loop silently —
    it is logged and the loop keeps polling until acquisition works again."""
    flaky = _ExplodingRedis(rds)
    log: list[int] = []

    async def work():
        log.append(1)

    task = asyncio.create_task(
        run_leader_loop("t_boom", work, interval=0.02, ttl=1, renew_interval=0.05, redis=flaky)
    )

    await asyncio.sleep(0.1)
    assert not task.done(), "loop must survive unexpected acquire errors"
    assert log == [], "must not run work while acquisition is failing"

    # Redis behaves again → the same loop acquires and does the work.
    flaky.broken = False
    await asyncio.sleep(0.15)
    assert len(log) >= 1

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


# ── startup one-shot gating (digest recovery) ────────────────────────────────


@pytest.mark.asyncio
async def test_digest_recovery_one_shot_runs_on_single_replica(rds, monkeypatch):
    """Two replicas booting in parallel → recover_digest_windows runs exactly
    once (the loser skips while the winner holds the lock)."""
    from whatisup import main as main_mod
    from whatisup.services import alert as alert_mod

    calls: list[int] = []
    gate = asyncio.Event()

    async def fake_recover():
        calls.append(1)
        await gate.wait()  # hold the lock while the other replica boots

    monkeypatch.setattr(alert_mod, "recover_digest_windows", fake_recover)

    t1 = asyncio.create_task(main_mod._recover_digests_once(redis=rds))
    t2 = asyncio.create_task(main_mod._recover_digests_once(redis=rds))
    await asyncio.sleep(0.05)  # both replicas have attempted acquisition
    gate.set()
    await asyncio.gather(t1, t2)

    assert len(calls) == 1, "stale digests must be recovered by one replica only"
    # The one-shot lock is released once done.
    assert await rds.get("whatisup:leader:digest_recovery") is None


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
