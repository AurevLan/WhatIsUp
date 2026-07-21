"""R-2 — Redis fail-open on the auth path.

``core/leader.py`` and the login lockout already tolerate a Redis outage; the
API-key auth paths in ``api/deps.py`` did not (any ``redis.get``/``setex``
raising bubbled up as a 500). These tests pin the fixed behavior: Redis down
degrades auth to a cache miss + bcrypt slow path, and the cache-eviction
helpers tolerate the outage too (stale entries are defused by the hash
fingerprint embedded in cache values and bounded by the 60 s TTL).
"""

from __future__ import annotations

import uuid

import bcrypt
import pytest
import pytest_asyncio
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy.ext.asyncio import AsyncSession

import whatisup.core.redis as redis_module
from whatisup.api.deps import (
    _auth_via_user_api_key,
    get_current_probe,
    invalidate_probe_auth_cache,
    invalidate_user_api_key_cache,
)
from whatisup.core.security import generate_probe_api_key
from whatisup.models.api_key import UserApiKey
from whatisup.models.probe import NetworkType, Probe
from whatisup.models.user import User


def _fast_hash(raw: str) -> str:
    """bcrypt rounds=4 — fast enough for tests, same verify path as production."""
    return bcrypt.hashpw(raw.encode(), bcrypt.gensalt(rounds=4)).decode()


class _BrokenRedis:
    """Every operation raises, like a down/unreachable Redis."""

    def __getattr__(self, name: str):
        async def _boom(*args: object, **kwargs: object) -> None:
            raise RedisConnectionError("Connection refused")

        return _boom


@pytest_asyncio.fixture
async def broken_redis(service_db: AsyncSession):
    """Swap the Redis singleton for a client that always raises.

    Depends on ``service_db`` so it runs after that fixture installed the fake
    client, and restores it afterwards for the fixture's own teardown.
    """
    prev = redis_module._redis
    redis_module._redis = _BrokenRedis()
    yield
    redis_module._redis = prev


@pytest.mark.asyncio
async def test_user_api_key_auth_survives_redis_outage(
    service_db: AsyncSession, test_user: User, broken_redis: None
) -> None:
    raw = "wiu_u_" + "a" * 32
    service_db.add(
        UserApiKey(
            user_id=test_user.id,
            name="failopen",
            key_hash=_fast_hash(raw),
            key_prefix=raw[:12],
            scopes=["read", "write"],
        )
    )
    await service_db.flush()

    # Depuis C2 la fonction rend aussi les portées de la clé : elles sont
    # vérifiées par `get_current_user`, qui seul connaît la méthode HTTP.
    user, scopes = await _auth_via_user_api_key(raw, service_db)
    assert user.id == test_user.id
    assert scopes == ["read", "write"]


@pytest.mark.asyncio
async def test_probe_auth_survives_redis_outage(
    service_db: AsyncSession, broken_redis: None
) -> None:
    key, prefix = generate_probe_api_key()
    probe = Probe(
        name="failopen-probe",
        location_name="DC",
        api_key_hash=_fast_hash(key),
        api_key_prefix=prefix,
        network_type=NetworkType.external,
    )
    service_db.add(probe)
    await service_db.flush()

    authed = await get_current_probe(x_probe_api_key=key, db=service_db)
    assert authed.id == probe.id


@pytest.mark.asyncio
async def test_invalidate_helpers_survive_redis_outage(
    service_db: AsyncSession, test_user: User, broken_redis: None
) -> None:
    """Rotation/revocation must not 500 because the cache eviction failed."""
    await invalidate_probe_auth_cache(uuid.uuid4())
    await invalidate_user_api_key_cache(uuid.uuid4())
