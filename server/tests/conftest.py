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
