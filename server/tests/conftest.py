"""Pytest fixtures for WhatIsUp server tests."""

from __future__ import annotations

import pytest_asyncio
from fakeredis.aioredis import FakeRedis
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import whatisup.core.redis as redis_module
from whatisup.core.database import get_db
from whatisup.core.limiter import limiter
from whatisup.main import app
from whatisup.models import Base
from whatisup.models.monitor import Monitor
from whatisup.models.probe import Probe
from whatisup.models.user import User

# SQLite in-memory for fast tests
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture(scope="session")
async def engine():
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(engine):
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def fake_redis():
    r = FakeRedis()
    yield r
    await r.aclose()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession, fake_redis: FakeRedis):
    """Test client with SQLite DB, fake Redis, and rate limiting disabled."""

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    redis_module._redis = fake_redis

    # Disable rate limiting for tests
    limiter.enabled = False

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

    limiter.enabled = True
    app.dependency_overrides.clear()
    redis_module._redis = None


# ── Service-layer fixtures ────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def service_db(db_session: AsyncSession, fake_redis: FakeRedis) -> AsyncSession:
    """DB session with fake Redis pre-wired — for direct service tests."""
    redis_module._redis = fake_redis
    yield db_session
    redis_module._redis = None


@pytest_asyncio.fixture
async def test_user(service_db: AsyncSession) -> User:
    u = User(email="svc@example.com", username="svcuser", hashed_password="x")
    service_db.add(u)
    await service_db.flush()
    return u


@pytest_asyncio.fixture
async def test_probe(service_db: AsyncSession) -> Probe:
    p = Probe(name="probe-test", location_name="Paris", api_key_hash="x")
    service_db.add(p)
    await service_db.flush()
    return p


@pytest_asyncio.fixture
async def test_monitor(service_db: AsyncSession, test_user: User) -> Monitor:
    m = Monitor(name="mon-test", url="http://example.com", owner_id=test_user.id)
    service_db.add(m)
    await service_db.flush()
    return m
