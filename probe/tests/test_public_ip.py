"""V2-02-07 — Tests for the probe's outbound public IP resolver."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from whatisup_probe.public_ip import (
    _query_resolver,
    reset_cache,
    resolve_public_ip,
)


@pytest.fixture(autouse=True)
def _reset_cache():
    reset_cache()
    yield
    reset_cache()


@pytest.mark.asyncio
async def test_resolve_public_ip_returns_first_success() -> None:
    """The first resolver to answer wins; subsequent are not tried."""
    mock_get = AsyncMock(return_value=httpx.Response(200, text="203.0.113.42"))
    with patch.object(httpx.AsyncClient, "get", mock_get):
        ip = await resolve_public_ip()
    assert ip == "203.0.113.42"
    # Called exactly once (first resolver answered)
    assert mock_get.await_count == 1


@pytest.mark.asyncio
async def test_resolve_public_ip_caches_across_calls() -> None:
    mock_get = AsyncMock(return_value=httpx.Response(200, text="1.2.3.4"))
    with patch.object(httpx.AsyncClient, "get", mock_get):
        first = await resolve_public_ip()
        second = await resolve_public_ip()
    assert first == "1.2.3.4"
    assert second == "1.2.3.4"
    # Second call hit cache, no new HTTP call
    assert mock_get.await_count == 1


@pytest.mark.asyncio
async def test_resolve_public_ip_falls_back_to_other_resolvers() -> None:
    # First resolver fails twice (max retries), second resolver succeeds.
    responses = [
        httpx.RequestError("boom"),
        httpx.RequestError("boom"),
        httpx.Response(200, text="9.9.9.9"),
    ]

    async def fake_get(*_args, **_kwargs):
        result = responses.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result

    with patch.object(httpx.AsyncClient, "get", side_effect=fake_get):
        ip = await resolve_public_ip()
    assert ip == "9.9.9.9"


@pytest.mark.asyncio
async def test_resolve_public_ip_returns_none_on_total_failure() -> None:
    async def always_fail(*_args, **_kwargs):
        raise httpx.RequestError("nope")

    with patch.object(httpx.AsyncClient, "get", side_effect=always_fail):
        ip = await resolve_public_ip()
    assert ip is None


@pytest.mark.asyncio
async def test_query_resolver_rejects_garbage_response() -> None:
    """Empty body / unreasonable length should be rejected."""

    async def fake_get_empty(*_args, **_kwargs):
        return httpx.Response(200, text="   ")

    async with httpx.AsyncClient() as client:
        with patch.object(client, "get", side_effect=fake_get_empty):
            ip = await _query_resolver(client, "https://example.com")
        assert ip is None
