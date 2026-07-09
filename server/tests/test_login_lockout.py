"""SA2 — per-account login lockout (Redis counters, anti-enumeration)."""

from __future__ import annotations

import pytest
from fakeredis.aioredis import FakeRedis
from httpx import AsyncClient
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import whatisup.services.lockout as lockout
from tests.conftest import TEST_PASSWORD
from whatisup.models.audit_log import AuditLog
from whatisup.models.user import User

LOGIN = "/api/v1/auth/login"
WRONG_PASSWORD = "WrongPassword9!"


async def _fail(client: AsyncClient, email: str, n: int = 1):
    """Submit n wrong-password attempts; return the last response."""
    last = None
    for _ in range(n):
        last = await client.post(LOGIN, data={"username": email, "password": WRONG_PASSWORD})
        assert last.status_code == 401
    return last


@pytest.mark.asyncio
async def test_lockout_after_threshold(client: AsyncClient, admin_user: User) -> None:
    """After LOCKOUT_THRESHOLD failures, even the correct password is rejected."""
    await _fail(client, admin_user.email, n=lockout.LOCKOUT_THRESHOLD)

    resp = await client.post(LOGIN, data={"username": admin_user.email, "password": TEST_PASSWORD})
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid credentials"


@pytest.mark.asyncio
async def test_locked_response_identical_to_wrong_password(
    client: AsyncClient, admin_user: User
) -> None:
    """Anti-enumeration: the locked-out response is byte-identical to a plain
    wrong-password response (status, body, WWW-Authenticate header)."""
    baseline = await _fail(client, admin_user.email, n=1)
    await _fail(client, admin_user.email, n=lockout.LOCKOUT_THRESHOLD - 1)

    locked = await client.post(
        LOGIN, data={"username": admin_user.email, "password": TEST_PASSWORD}
    )
    assert locked.status_code == baseline.status_code == 401
    assert locked.json() == baseline.json()
    assert locked.headers.get("www-authenticate") == baseline.headers.get("www-authenticate")

    # Unknown identifiers go through the same pipeline — same response again.
    unknown = await client.post(
        LOGIN, data={"username": "ghost@nowhere.test", "password": WRONG_PASSWORD}
    )
    assert unknown.status_code == 401
    assert unknown.json() == baseline.json()


@pytest.mark.asyncio
async def test_counter_reset_on_success(client: AsyncClient, admin_user: User) -> None:
    """A successful login clears the failure counter — failures don't accumulate
    across successful logins."""
    await _fail(client, admin_user.email, n=lockout.LOCKOUT_THRESHOLD - 1)

    ok = await client.post(LOGIN, data={"username": admin_user.email, "password": TEST_PASSWORD})
    assert ok.status_code == 200

    # Counter was reset: N-1 new failures still don't lock the account.
    await _fail(client, admin_user.email, n=lockout.LOCKOUT_THRESHOLD - 1)
    ok2 = await client.post(LOGIN, data={"username": admin_user.email, "password": TEST_PASSWORD})
    assert ok2.status_code == 200


@pytest.mark.asyncio
async def test_lockout_expiry_unlocks(
    client: AsyncClient, admin_user: User, fake_redis: FakeRedis
) -> None:
    """The lock key carries the lockout TTL; once it expires, login works again."""
    await _fail(client, admin_user.email, n=lockout.LOCKOUT_THRESHOLD)

    lock_key = lockout.lock_key(admin_user.email)
    assert await fake_redis.exists(lock_key)
    ttl = await fake_redis.ttl(lock_key)
    assert 0 < ttl <= lockout.LOCKOUT_DURATION_SECONDS

    # Simulate TTL expiry.
    await fake_redis.delete(lock_key)

    resp = await client.post(LOGIN, data={"username": admin_user.email, "password": TEST_PASSWORD})
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_lockout_trigger_writes_audit_entry(
    client: AsyncClient, admin_user: User, db_session: AsyncSession
) -> None:
    """Exactly one audit entry is written when the lockout triggers."""
    await _fail(client, admin_user.email, n=lockout.LOCKOUT_THRESHOLD + 2)

    rows = (
        (await db_session.execute(select(AuditLog).where(AuditLog.action == "user.login_lockout")))
        .scalars()
        .all()
    )
    assert len(rows) == 1
    entry = rows[0]
    assert entry.object_id == admin_user.id
    assert entry.object_name == admin_user.username
    assert entry.diff["threshold"] == lockout.LOCKOUT_THRESHOLD


@pytest.mark.asyncio
async def test_identifier_normalization(client: AsyncClient, admin_user: User) -> None:
    """Case/whitespace variants of the identifier share the same counter."""
    await _fail(client, admin_user.email.upper(), n=lockout.LOCKOUT_THRESHOLD)

    resp = await client.post(LOGIN, data={"username": admin_user.email, "password": TEST_PASSWORD})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_totp_flow_resets_counter_at_password_step(
    client: AsyncClient, regular_user: User, db_session: AsyncSession, fake_redis: FakeRedis
) -> None:
    """With 2FA enabled, a correct password still returns the MFA challenge and
    clears the failure counter (lockout applies to the password step only)."""
    regular_user.totp_enabled = True
    await db_session.flush()

    await _fail(client, regular_user.email, n=lockout.LOCKOUT_THRESHOLD - 1)

    resp = await client.post(
        LOGIN, data={"username": regular_user.email, "password": TEST_PASSWORD}
    )
    assert resp.status_code == 200
    assert resp.json()["mfa_required"] is True
    assert not await fake_redis.exists(lockout.fail_key(regular_user.email))


@pytest.mark.asyncio
async def test_fail_counter_always_carries_ttl(
    client: AsyncClient, admin_user: User, fake_redis: FakeRedis
) -> None:
    """R2: the failure counter must always carry a TTL — even on the very first
    failure, which the atomic INCR/EXPIRE pipeline guarantees."""
    await _fail(client, admin_user.email, n=1)

    fkey = lockout.fail_key(admin_user.email)
    assert int(await fake_redis.get(fkey)) == 1
    ttl = await fake_redis.ttl(fkey)
    assert 0 < ttl <= lockout.LOCKOUT_WINDOW_SECONDS


@pytest.mark.asyncio
async def test_ttl_self_heals_immortal_counter(
    client: AsyncClient, admin_user: User, fake_redis: FakeRedis
) -> None:
    """R2 regression guard ("immortal counter"): if a counter is ever left
    WITHOUT a TTL (e.g. a lost EXPIRE after a Redis blip), the next failure must
    re-apply the window. On the pre-fix code (EXPIRE only when count == 1) the
    key stayed TTL-less forever and re-locked the user on every later failure;
    the atomic ``EXPIRE ... NX`` self-heals it."""
    fkey = lockout.fail_key(admin_user.email)
    # Simulate a counter mid-window with NO expiry (the bug condition).
    await fake_redis.set(fkey, 5)
    assert await fake_redis.ttl(fkey) == -1  # -1 == key exists but no TTL

    await _fail(client, admin_user.email, n=1)

    assert int(await fake_redis.get(fkey)) == 6
    ttl = await fake_redis.ttl(fkey)
    assert 0 < ttl <= lockout.LOCKOUT_WINDOW_SECONDS


@pytest.mark.asyncio
async def test_unknown_account_burns_bcrypt(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R3: an unknown / inactive account still runs a bcrypt verification so its
    response timing matches a wrong password on a real account (no timing oracle
    to enumerate valid emails)."""
    import whatisup.api.v1.auth as auth_module

    calls = {"n": 0}
    original = auth_module._burn_password_check

    async def _spy(password: str) -> None:
        calls["n"] += 1
        await original(password)

    monkeypatch.setattr(auth_module, "_burn_password_check", _spy)

    resp = await client.post(
        LOGIN, data={"username": "ghost@nowhere.test", "password": WRONG_PASSWORD}
    )
    assert resp.status_code == 401
    assert calls["n"] == 1


class _BrokenRedis:
    """Every awaited call raises RedisError — simulates Redis being down.

    Also models the pipeline API used by ``register_failure`` so the fail-open
    path is exercised realistically: queued commands are no-ops and ``execute``
    raises, just like a real client whose connection drops mid-transaction.
    """

    def __getattr__(self, name):
        async def _boom(*args, **kwargs):
            raise RedisError("redis down")

        return _boom

    def pipeline(self, *args, **kwargs):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def incr(self, *args, **kwargs):
        return self

    def expire(self, *args, **kwargs):
        return self

    async def execute(self):
        raise RedisError("redis down")


@pytest.mark.asyncio
async def test_fail_open_when_redis_down(
    client: AsyncClient, admin_user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Redis unavailable → lockout is skipped entirely; login keeps working."""
    monkeypatch.setattr(lockout, "get_redis", lambda: _BrokenRedis())

    await _fail(client, admin_user.email, n=lockout.LOCKOUT_THRESHOLD + 5)

    resp = await client.post(LOGIN, data={"username": admin_user.email, "password": TEST_PASSWORD})
    assert resp.status_code == 200
    assert "access_token" in resp.json()
