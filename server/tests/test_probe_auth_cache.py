"""Probe auth cache hardening (SA6) — rotate-key re-cache race.

``rotate-key`` commits the new hash BEFORE evicting the Redis auth cache
(order fixed in 8bb61d2). Residual variant closed here: a bcrypt slow path
already in flight during the commit (candidate row read with the OLD hash)
could re-cache the old key AFTER the eviction, re-authenticating it for
another TTL. Two complementary defenses are pinned by these tests:

1. Cache values embed a fingerprint of the bcrypt hash the key was verified
   against; the fast path re-checks it against the probe row it loads anyway
   (zero extra DB read) and evicts on mismatch.
2. The slow path re-reads the live hash just before the cache write and skips
   the write if the verified credential is no longer current.

Plus the ordering pin: rotate-key must commit BEFORE evicting the cache.
"""

from __future__ import annotations

import hashlib

import bcrypt
import pytest
import pytest_asyncio
from fakeredis.aioredis import FakeRedis
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

import whatisup.api.deps as deps
import whatisup.api.v1.probes as probes_mod
from whatisup.core.security import generate_probe_api_key
from whatisup.models.probe import NetworkType, Probe

HEARTBEAT = "/api/v1/probes/heartbeat"


def _fast_hash(raw: str) -> str:
    """bcrypt rounds=4 — fast enough for tests, same verify path as production."""
    return bcrypt.hashpw(raw.encode(), bcrypt.gensalt(rounds=4)).decode()


def _forward_cache_key(raw_key: str) -> str:
    """Replicate the forward cache key derivation of deps.get_current_probe."""
    digest = hashlib.sha256(raw_key.encode(), usedforsecurity=False).hexdigest()[:32]
    return f"whatisup:probe_auth:{digest}"


async def _get_str(redis: FakeRedis, key: str) -> str | None:
    val = await redis.get(key)
    if isinstance(val, bytes):
        return val.decode()
    return val


async def _make_probe(db: AsyncSession, name: str) -> tuple[Probe, str]:
    """Create a new-scheme probe (``wiu_<prefix>.<secret>``)."""
    key, prefix = generate_probe_api_key()
    probe = Probe(
        name=name,
        location_name="DC",
        api_key_hash=_fast_hash(key),
        api_key_prefix=prefix,
        network_type=NetworkType.external,
    )
    db.add(probe)
    await db.flush()
    return probe, key


@pytest_asyncio.fixture
def count_bcrypt(monkeypatch):
    """Spy on ``deps.verify_api_key`` and count how many bcrypt checks run."""
    calls = {"n": 0}
    real = deps.verify_api_key

    def _wrapped(api_key: str, hashed: str) -> bool:
        calls["n"] += 1
        return real(api_key, hashed)

    monkeypatch.setattr(deps, "verify_api_key", _wrapped)
    return calls


# ── Nominal path: fingerprinted cache write + free fast path ─────────────────


@pytest.mark.asyncio
async def test_nominal_auth_writes_fingerprinted_cache_then_fast_path(
    client: AsyncClient, db_session: AsyncSession, fake_redis: FakeRedis, count_bcrypt: dict
) -> None:
    """Slow path caches ``probe_id|fingerprint``; second auth is a pure cache hit."""
    probe, key = await _make_probe(db_session, "sa6-nominal")

    r1 = await client.post(HEARTBEAT, json={}, headers={"X-Probe-Api-Key": key})
    assert r1.status_code == 200, r1.text
    assert count_bcrypt["n"] == 1

    cached = await _get_str(fake_redis, _forward_cache_key(key))
    assert cached is not None
    cached_id, sep, cached_fp = cached.partition("|")
    assert sep == "|", "cache value must embed a hash fingerprint (SA6)"
    assert cached_id == str(probe.id)
    assert cached_fp == deps._probe_hash_fingerprint(probe.api_key_hash)
    # Reverse index present for precise eviction on rotation.
    assert await _get_str(fake_redis, f"whatisup:probe_auth_rev:{probe.id}") is not None

    # Cache hit: zero additional bcrypt, no cache rewrite needed.
    r2 = await client.post(HEARTBEAT, json={}, headers={"X-Probe-Api-Key": key})
    assert r2.status_code == 200, r2.text
    assert count_bcrypt["n"] == 1, "fast path must not re-run bcrypt"


@pytest.mark.asyncio
async def test_pre_fingerprint_cache_value_treated_as_miss(
    client: AsyncClient, db_session: AsyncSession, fake_redis: FakeRedis, count_bcrypt: dict
) -> None:
    """Deploy compat: a legacy bare ``probe_id`` cache value (pre-SA6 format) is
    evicted and re-authenticated via the slow path, then rewritten fingerprinted."""
    probe, key = await _make_probe(db_session, "sa6-legacyval")
    await fake_redis.setex(_forward_cache_key(key), 60, str(probe.id))

    resp = await client.post(HEARTBEAT, json={}, headers={"X-Probe-Api-Key": key})
    assert resp.status_code == 200, resp.text
    assert count_bcrypt["n"] == 1  # slow path, not blind trust in the bare id

    cached = await _get_str(fake_redis, _forward_cache_key(key))
    assert cached == f"{probe.id}|{deps._probe_hash_fingerprint(probe.api_key_hash)}"


# ── The SA6 race: slow path in flight during rotation ─────────────────────────


@pytest.mark.asyncio
async def test_inflight_slow_path_does_not_recache_old_key(
    client: AsyncClient,
    db_session: AsyncSession,
    fake_redis: FakeRedis,
    monkeypatch,
) -> None:
    """A bcrypt verification in flight while rotate-key commits must NOT re-cache
    the old key.

    The request read the candidate row (OLD hash) before the rotation commit and
    verifies successfully against that stale snapshot. The rotation lands
    mid-bcrypt (simulated by swapping hash+prefix inside the verify call; the
    guarded write's re-read sees it via autoflush, standing in for the
    concurrently committed transaction). Without the guard, ``_accept`` would
    re-cache the old key for another TTL — after the rotation's eviction.
    """
    probe, old_key = await _make_probe(db_session, "sa6-race")
    new_key, new_prefix = generate_probe_api_key()
    new_hash = _fast_hash(new_key)

    real_verify = deps.verify_api_key

    def _rotation_lands_mid_bcrypt(api_key: str, hashed: str) -> bool:
        ok = real_verify(api_key, hashed)  # verified against the OLD hash snapshot
        probe.api_key_hash = new_hash
        probe.api_key_prefix = new_prefix
        return ok

    monkeypatch.setattr(deps, "verify_api_key", _rotation_lands_mid_bcrypt)

    resp = await client.post(HEARTBEAT, json={}, headers={"X-Probe-Api-Key": old_key})
    # The in-flight request itself may complete (it started pre-rotation)…
    assert resp.status_code == 200, resp.text
    # …but it must not have written any cache entry for the old key.
    assert await fake_redis.get(_forward_cache_key(old_key)) is None, (
        "slow path re-cached a credential that was rotated mid-verification"
    )
    assert await fake_redis.get(f"whatisup:probe_auth_rev:{probe.id}") is None

    # The very next attempt with the old key is rejected.
    monkeypatch.setattr(deps, "verify_api_key", real_verify)
    resp2 = await client.post(HEARTBEAT, json={}, headers={"X-Probe-Api-Key": old_key})
    assert resp2.status_code == 401, resp2.text


@pytest.mark.asyncio
async def test_stale_fingerprint_entry_rejected_and_evicted(
    client: AsyncClient,
    db_session: AsyncSession,
    admin_token: str,
    fake_redis: FakeRedis,
) -> None:
    """Belt to the suspender: even if a stale entry somehow lands in Redis AFTER
    the rotation's eviction (the lost-race outcome), the fast path detects the
    fingerprint mismatch against the live hash, evicts it and rejects the key."""
    probe, old_key = await _make_probe(db_session, "sa6-stale")
    old_fp = deps._probe_hash_fingerprint(probe.api_key_hash)

    warm = await client.post(HEARTBEAT, json={}, headers={"X-Probe-Api-Key": old_key})
    assert warm.status_code == 200, warm.text

    rot = await client.post(
        f"/api/v1/probes/{probe.id}/rotate-key",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert rot.status_code == 200, rot.text
    assert await fake_redis.get(_forward_cache_key(old_key)) is None  # evicted

    # Simulate the lost race: stale forward entry re-written post-eviction.
    await fake_redis.setex(_forward_cache_key(old_key), 60, f"{probe.id}|{old_fp}")

    resp = await client.post(HEARTBEAT, json={}, headers={"X-Probe-Api-Key": old_key})
    assert resp.status_code == 401, resp.text
    assert await fake_redis.get(_forward_cache_key(old_key)) is None, (
        "stale fingerprinted entry must be evicted on sight"
    )

    # And the new key still authenticates normally.
    new_key = rot.json()["api_key"]
    ok = await client.post(HEARTBEAT, json={}, headers={"X-Probe-Api-Key": new_key})
    assert ok.status_code == 200, ok.text


# ── Ordering pin: rotate-key must commit BEFORE evicting the cache ───────────


@pytest.mark.asyncio
async def test_rotate_key_commits_before_cache_eviction(
    client: AsyncClient,
    db_session: AsyncSession,
    admin_token: str,
    fake_redis: FakeRedis,
    monkeypatch,
) -> None:
    """Regression pin for 8bb61d2: evicting BEFORE the commit re-opens the race
    (an old-key cache miss between eviction and commit re-authenticates against
    the still-committed OLD hash and re-populates the cache)."""
    probe, _key = await _make_probe(db_session, "sa6-order")

    order: list[str] = []
    orig_commit = db_session.commit

    async def _spy_commit():
        order.append("commit")
        await orig_commit()

    monkeypatch.setattr(db_session, "commit", _spy_commit)

    orig_evict = probes_mod.invalidate_probe_auth_cache

    async def _spy_evict(probe_id):
        order.append("evict")
        await orig_evict(probe_id)

    monkeypatch.setattr(probes_mod, "invalidate_probe_auth_cache", _spy_evict)

    rot = await client.post(
        f"/api/v1/probes/{probe.id}/rotate-key",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert rot.status_code == 200, rot.text
    assert "commit" in order, "rotate-key must commit the new hash"
    assert "evict" in order, "rotate-key must evict the probe-auth cache"
    assert order.index("commit") < order.index("evict"), (
        "rotate-key must commit the new hash BEFORE evicting the auth cache — "
        "evict-first re-opens the old-key re-cache race (cf. 8bb61d2)"
    )
