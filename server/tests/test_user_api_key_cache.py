"""User API-key auth cache hardening (S4) — mirrors probe SA6 (test_probe_auth_cache).

The user API-key fast path caches ``SHA-256(raw_key) → user_id`` in Redis (TTL
60s). Before this change a *revoked* key kept authenticating on the fast path for
up to one TTL, because the cache was never evicted on revocation and the fast
path re-validated only ``User.is_active`` — never the key's ``is_revoked`` flag.

Two complementary defenses are pinned here (same shape as probe SA6):

1. Cache values embed ``user_id|key_id|fingerprint`` where the fingerprint is a
   SHA-256[:16] of the bcrypt hash the key was verified against. The fast path
   re-loads the live key row (checking ``is_revoked`` / ``expires_at``) and
   compares the fingerprint with ``hmac.compare_digest`` — evicting on mismatch.
2. The slow path re-reads the live key row just before the cache write and skips
   the write if the credential is no longer valid (in-flight-bcrypt race).

Plus: revoke evicts the cache immediately (reverse index) and must commit BEFORE
evicting (ordering pin).
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
import whatisup.api.v1.api_keys as api_keys_mod
from whatisup.core.security import generate_user_api_key
from whatisup.models.api_key import UserApiKey
from whatisup.models.user import User

# Any get_current_user endpoint exercises the user-API-key auth path.
AUTH_ENDPOINT = "/api/v1/api-keys/"


def _fast_hash(raw: str) -> str:
    """bcrypt rounds=4 — fast for tests, same verify path as production."""
    return bcrypt.hashpw(raw.encode(), bcrypt.gensalt(rounds=4)).decode()


def _forward_cache_key(raw_key: str) -> str:
    """Replicate the forward cache key derivation of deps._auth_via_user_api_key."""
    digest = hashlib.sha256(raw_key.encode(), usedforsecurity=False).hexdigest()[:32]
    return f"whatisup:user_api:{digest}"


async def _get_str(redis: FakeRedis, key: str) -> str | None:
    val = await redis.get(key)
    if isinstance(val, bytes):
        return val.decode()
    return val


async def _make_user_key(db: AsyncSession, user: User, name: str = "k") -> tuple[UserApiKey, str]:
    raw = generate_user_api_key()
    row = UserApiKey(
        user_id=user.id,
        name=name,
        key_hash=_fast_hash(raw),
        key_prefix=raw[:12],
    )
    db.add(row)
    await db.flush()
    return row, raw


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


# ── Nominal: fingerprinted cache write + free fast path ──────────────────────


@pytest.mark.asyncio
async def test_nominal_auth_writes_fingerprinted_cache_then_fast_path(
    client: AsyncClient,
    db_session: AsyncSession,
    admin_user: User,
    fake_redis: FakeRedis,
    count_bcrypt: dict,
) -> None:
    row, raw = await _make_user_key(db_session, admin_user, "nominal")

    r1 = await client.get(AUTH_ENDPOINT, headers={"X-Api-Key": raw})
    assert r1.status_code == 200, r1.text
    assert count_bcrypt["n"] == 1

    cached = await _get_str(fake_redis, _forward_cache_key(raw))
    assert cached is not None
    parts = cached.split("|")
    assert len(parts) == 3, "cache value must embed user_id|key_id|fingerprint (S4)"
    assert parts[0] == str(admin_user.id)
    assert parts[1] == str(row.id)
    assert parts[2] == deps._hash_fingerprint(row.key_hash)
    # Reverse index present for precise eviction on revocation.
    assert await _get_str(fake_redis, f"whatisup:user_api_rev:{row.id}") is not None

    # Cache hit: zero additional bcrypt.
    r2 = await client.get(AUTH_ENDPOINT, headers={"X-Api-Key": raw})
    assert r2.status_code == 200, r2.text
    assert count_bcrypt["n"] == 1, "fast path must not re-run bcrypt"


@pytest.mark.asyncio
async def test_pre_s4_bare_cache_value_treated_as_miss(
    client: AsyncClient,
    db_session: AsyncSession,
    admin_user: User,
    fake_redis: FakeRedis,
    count_bcrypt: dict,
) -> None:
    """Deploy compat: a legacy bare ``user_id`` cache value (pre-S4 format) is
    evicted and re-authenticated via the slow path, then rewritten fingerprinted."""
    row, raw = await _make_user_key(db_session, admin_user, "legacyval")
    await fake_redis.setex(_forward_cache_key(raw), 60, str(admin_user.id))

    resp = await client.get(AUTH_ENDPOINT, headers={"X-Api-Key": raw})
    assert resp.status_code == 200, resp.text
    assert count_bcrypt["n"] == 1  # slow path, not blind trust in the bare id

    cached = await _get_str(fake_redis, _forward_cache_key(raw))
    assert cached == f"{admin_user.id}|{row.id}|{deps._hash_fingerprint(row.key_hash)}"


# ── The core gap: revoked key must be rejected immediately ───────────────────


@pytest.mark.asyncio
async def test_revoked_key_rejected_immediately(
    client: AsyncClient,
    db_session: AsyncSession,
    admin_user: User,
    admin_token: str,
    fake_redis: FakeRedis,
) -> None:
    """A revoked key stops authenticating on sight — no waiting for the cache TTL.

    Pre-fix: revoke never evicted the cache and the fast path re-checked only
    ``User.is_active``, so this returned 200 until the entry expired.
    """
    row, raw = await _make_user_key(db_session, admin_user, "revokeme")

    warm = await client.get(AUTH_ENDPOINT, headers={"X-Api-Key": raw})
    assert warm.status_code == 200, warm.text
    assert await fake_redis.get(_forward_cache_key(raw)) is not None

    rev = await client.delete(
        f"/api/v1/api-keys/{row.id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert rev.status_code == 204, rev.text
    # Forward entry + reverse index evicted immediately.
    assert await fake_redis.get(_forward_cache_key(raw)) is None
    assert await fake_redis.get(f"whatisup:user_api_rev:{row.id}") is None

    resp = await client.get(AUTH_ENDPOINT, headers={"X-Api-Key": raw})
    assert resp.status_code == 401, resp.text


@pytest.mark.asyncio
async def test_inflight_slow_path_does_not_recache_revoked_key(
    client: AsyncClient,
    db_session: AsyncSession,
    admin_user: User,
    fake_redis: FakeRedis,
    monkeypatch,
) -> None:
    """A bcrypt verification in flight while the key is revoked must NOT re-cache.

    The request read the key row (still active) before the revocation and verifies
    successfully against that snapshot. The revocation lands mid-bcrypt (simulated
    by flipping ``is_revoked`` inside the verify call; the guarded write's re-read
    sees it via autoflush, standing in for the concurrently committed transaction).
    Without the guard, the slow path would re-cache the revoked key for another TTL.
    """
    row, raw = await _make_user_key(db_session, admin_user, "race")

    real_verify = deps.verify_api_key

    def _revocation_lands_mid_bcrypt(api_key: str, hashed: str) -> bool:
        ok = real_verify(api_key, hashed)
        row.is_revoked = True  # revocation commits mid-verification
        return ok

    monkeypatch.setattr(deps, "verify_api_key", _revocation_lands_mid_bcrypt)

    resp = await client.get(AUTH_ENDPOINT, headers={"X-Api-Key": raw})
    # The in-flight request itself may complete (it started pre-revocation)…
    assert resp.status_code == 200, resp.text
    # …but it must not have written any cache entry for the revoked key.
    assert await fake_redis.get(_forward_cache_key(raw)) is None, (
        "slow path re-cached a credential that was revoked mid-verification"
    )
    assert await fake_redis.get(f"whatisup:user_api_rev:{row.id}") is None

    # The very next attempt is rejected (real verify + is_revoked filter).
    monkeypatch.setattr(deps, "verify_api_key", real_verify)
    resp2 = await client.get(AUTH_ENDPOINT, headers={"X-Api-Key": raw})
    assert resp2.status_code == 401, resp2.text


@pytest.mark.asyncio
async def test_stale_fingerprint_entry_rejected_and_evicted(
    client: AsyncClient,
    db_session: AsyncSession,
    admin_user: User,
    fake_redis: FakeRedis,
    count_bcrypt: dict,
) -> None:
    """Belt: a forward entry whose fingerprint doesn't match the live key hash is
    a cache miss (``hmac.compare_digest`` negative), evicted, and re-authenticated
    via the slow path — a stale/forged value can never short-circuit auth."""
    row, raw = await _make_user_key(db_session, admin_user, "stalefp")
    # Correct user_id|key_id but a bogus fingerprint (never matches the live hash).
    await fake_redis.setex(
        _forward_cache_key(raw), 60, f"{admin_user.id}|{row.id}|deadbeefdeadbeef"
    )

    resp = await client.get(AUTH_ENDPOINT, headers={"X-Api-Key": raw})
    assert resp.status_code == 200, resp.text
    assert count_bcrypt["n"] == 1, "fingerprint mismatch must fall through to bcrypt"

    # Rewritten with the correct fingerprint.
    cached = await _get_str(fake_redis, _forward_cache_key(raw))
    assert cached == f"{admin_user.id}|{row.id}|{deps._hash_fingerprint(row.key_hash)}"


# ── Ordering pin: revoke must commit BEFORE evicting the cache ───────────────


@pytest.mark.asyncio
async def test_revoke_commits_before_cache_eviction(
    client: AsyncClient,
    db_session: AsyncSession,
    admin_user: User,
    admin_token: str,
    fake_redis: FakeRedis,
    monkeypatch,
) -> None:
    """Evicting BEFORE the commit re-opens the race (a cache miss between eviction
    and commit re-authenticates against the still-active row and re-populates)."""
    row, _raw = await _make_user_key(db_session, admin_user, "order")

    order: list[str] = []
    orig_commit = db_session.commit

    async def _spy_commit():
        order.append("commit")
        await orig_commit()

    monkeypatch.setattr(db_session, "commit", _spy_commit)

    orig_evict = api_keys_mod.invalidate_user_api_key_cache

    async def _spy_evict(key_id):
        order.append("evict")
        await orig_evict(key_id)

    monkeypatch.setattr(api_keys_mod, "invalidate_user_api_key_cache", _spy_evict)

    rev = await client.delete(
        f"/api/v1/api-keys/{row.id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert rev.status_code == 204, rev.text
    assert "commit" in order, "revoke must commit the is_revoked flag"
    assert "evict" in order, "revoke must evict the user-api auth cache"
    assert order.index("commit") < order.index("evict"), (
        "revoke must commit the revocation BEFORE evicting the auth cache — "
        "evict-first re-opens the revoked-key re-cache race"
    )
