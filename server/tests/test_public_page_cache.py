"""Public status page cache + check_results index alignment (plan V2, A-0 bis).

The ``/public/pages/{slug}/monitors`` payload aggregates 90 days of raw
check_results for every monitor of the page (~9.5 s measured on 4.9M rows) and
is served unauthenticated at 60 req/min. These tests pin the memoisation that
closes that amplification path, and its fail-open behaviour: a Redis outage
must degrade to a slow page, never to an error page.
"""

from __future__ import annotations

import pytest
from fakeredis.aioredis import FakeRedis
from httpx import AsyncClient
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex

from whatisup.api.v1.public import PUBLIC_MONITORS_CACHE_TTL
from whatisup.models.result import CheckResult


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _make_page(client: AsyncClient, token: str, name: str, slug: str) -> str:
    grp = (
        await client.post(
            "/api/v1/groups/",
            json={"name": name, "public_slug": slug},
            headers=_auth(token),
        )
    ).json()
    return grp["id"]


async def _add_monitor(client: AsyncClient, token: str, group_id: str, name: str) -> None:
    await client.post(
        "/api/v1/monitors/",
        json={"name": name, "url": "https://example.com", "group_id": group_id},
        headers=_auth(token),
    )


# ---------------------------------------------------------------------------
# Cache behaviour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_public_monitors_payload_is_cached(
    client: AsyncClient, user_token: str, fake_redis: FakeRedis
) -> None:
    """A second request is served from Redis, not recomputed from check_results."""
    gid = await _make_page(client, user_token, "CacheGroup", "cachegroup")
    await _add_monitor(client, user_token, gid, "Mon1")

    first = await client.get("/api/v1/public/pages/cachegroup/monitors")
    assert first.status_code == 200
    assert [m["name"] for m in first.json()] == ["Mon1"]

    cache_key = f"whatisup:public:monitors:v2:{gid}"
    assert await fake_redis.exists(cache_key)
    ttl = await fake_redis.ttl(cache_key)
    assert 0 < ttl <= PUBLIC_MONITORS_CACHE_TTL

    # A monitor added behind the cache stays invisible until the TTL lapses —
    # that staleness is the deliberate trade-off, so assert it rather than
    # letting a future change silently turn the cache into a no-op.
    await _add_monitor(client, user_token, gid, "Mon2")
    cached = await client.get("/api/v1/public/pages/cachegroup/monitors")
    assert [m["name"] for m in cached.json()] == ["Mon1"]

    await fake_redis.delete(cache_key)
    fresh = await client.get("/api/v1/public/pages/cachegroup/monitors")
    assert sorted(m["name"] for m in fresh.json()) == ["Mon1", "Mon2"]


@pytest.mark.asyncio
async def test_public_monitors_cache_is_scoped_per_page(
    client: AsyncClient, user_token: str
) -> None:
    """Two status pages must never serve each other's monitors."""
    gid_a = await _make_page(client, user_token, "GroupA", "group-a")
    gid_b = await _make_page(client, user_token, "GroupB", "group-b")
    await _add_monitor(client, user_token, gid_a, "OnlyA")
    await _add_monitor(client, user_token, gid_b, "OnlyB")

    a = await client.get("/api/v1/public/pages/group-a/monitors")
    b = await client.get("/api/v1/public/pages/group-b/monitors")

    assert [m["name"] for m in a.json()] == ["OnlyA"]
    assert [m["name"] for m in b.json()] == ["OnlyB"]


@pytest.mark.asyncio
async def test_public_monitors_empty_page_is_not_cached(
    client: AsyncClient, user_token: str, fake_redis: FakeRedis
) -> None:
    """A page whose first monitor was just added must not stay blank for a TTL."""
    gid = await _make_page(client, user_token, "EmptyGroup", "emptygroup")

    empty = await client.get("/api/v1/public/pages/emptygroup/monitors")
    assert empty.status_code == 200
    assert empty.json() == []
    assert not await fake_redis.exists(f"whatisup:public:monitors:v2:{gid}")

    await _add_monitor(client, user_token, gid, "FirstMon")
    filled = await client.get("/api/v1/public/pages/emptygroup/monitors")
    assert [m["name"] for m in filled.json()] == ["FirstMon"]


@pytest.mark.asyncio
async def test_public_monitors_survives_redis_outage(
    client: AsyncClient, user_token: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Redis down → the page is slow, not broken (fail-open helpers)."""
    gid = await _make_page(client, user_token, "OutageGroup", "outagegroup")
    await _add_monitor(client, user_token, gid, "OutageMon")

    import whatisup.core.redis as redis_module

    class _DeadRedis:
        async def get(self, *_a, **_kw):
            raise RedisConnectionError("redis is down")

        async def setex(self, *_a, **_kw):
            raise RedisConnectionError("redis is down")

    monkeypatch.setattr(redis_module, "get_redis", lambda: _DeadRedis())

    resp = await client.get("/api/v1/public/pages/outagegroup/monitors")
    assert resp.status_code == 200
    assert [m["name"] for m in resp.json()] == ["OutageMon"]


# ---------------------------------------------------------------------------
# Model ↔ database index alignment
# ---------------------------------------------------------------------------


def test_check_result_indexes_match_the_database() -> None:
    """Guard the realignment done in migration f2a3b4c5d6e7.

    The model used to declare two indexes the database no longer has, while
    omitting the two it does have — so `alembic revision --autogenerate` would
    have proposed dropping 428 MB and 216 kB of live indexes and recreating
    852 MB of dead ones.
    """
    by_name = {ix.name: ix for ix in CheckResult.__table__.indexes}
    assert set(by_name) == {"ix_check_results_monitor_checked", "ix_cr_checked_at_brin"}

    # The DESC ordering must survive: autogenerate compares index expressions,
    # so dropping it here makes alembic propose rebuilding a 428 MB index as
    # ASC — and fetch_latest_results' LATERAL depends on the descending order.
    ddl = str(
        CreateIndex(by_name["ix_check_results_monitor_checked"]).compile(
            dialect=postgresql.dialect()
        )
    )
    assert "monitor_id" in ddl
    assert "checked_at DESC" in ddl

    assert [c.name for c in by_name["ix_cr_checked_at_brin"].columns] == ["checked_at"]
    assert by_name["ix_cr_checked_at_brin"].dialect_options["postgresql"]["using"] == "brin"
