"""Tests for custom_headers wiring + default User-Agent in the HTTP checker."""

from __future__ import annotations

import httpx
import pytest
import respx

from whatisup_probe.checkers import perform_check
from whatisup_probe.checkers._shared import DEFAULT_USER_AGENT


@pytest.mark.asyncio
@respx.mock
async def test_custom_headers_are_sent() -> None:
    route = respx.get("https://example.com").mock(return_value=httpx.Response(200))
    result = await perform_check(
        monitor_id="m1",
        url="https://example.com",
        timeout_seconds=5,
        follow_redirects=True,
        expected_status_codes=[200],
        ssl_check_enabled=False,
        custom_headers={"User-Agent": "Mozilla/5.0 (custom)", "X-Trace": "abc"},
    )
    assert result.status == "up"
    assert route.called
    sent = route.calls.last.request.headers
    assert sent["user-agent"] == "Mozilla/5.0 (custom)"
    assert sent["x-trace"] == "abc"


@pytest.mark.asyncio
@respx.mock
async def test_default_user_agent_when_no_custom_headers() -> None:
    route = respx.get("https://example.com").mock(return_value=httpx.Response(200))
    result = await perform_check(
        monitor_id="m2",
        url="https://example.com",
        timeout_seconds=5,
        follow_redirects=True,
        expected_status_codes=[200],
        ssl_check_enabled=False,
    )
    assert result.status == "up"
    sent = route.calls.last.request.headers
    assert sent["user-agent"] == DEFAULT_USER_AGENT


@pytest.mark.asyncio
@respx.mock
async def test_keyword_check_with_custom_headers() -> None:
    route = respx.get("https://example.com").mock(return_value=httpx.Response(200, text="welcome"))
    result = await perform_check(
        monitor_id="m3",
        url="https://example.com",
        timeout_seconds=5,
        follow_redirects=True,
        expected_status_codes=[200],
        ssl_check_enabled=False,
        check_type="keyword",
        keyword="welcome",
        custom_headers={"Authorization": "Bearer xyz"},
    )
    assert result.status == "up"
    assert route.calls.last.request.headers["authorization"] == "Bearer xyz"
