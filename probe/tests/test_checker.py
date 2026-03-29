"""Tests for the HTTP check engine."""

from __future__ import annotations

import httpx
import pytest
import respx

from whatisup_probe.checkers import perform_check


@pytest.mark.asyncio
@respx.mock
async def test_check_up_200() -> None:
    respx.get("https://example.com").mock(return_value=httpx.Response(200))
    result = await perform_check(
        monitor_id="test-monitor",
        url="https://example.com",
        timeout_seconds=10,
        follow_redirects=True,
        expected_status_codes=[200],
        ssl_check_enabled=False,
    )
    assert result.status == "up"
    assert result.http_status == 200
    assert result.response_time_ms is not None
    assert result.response_time_ms >= 0


@pytest.mark.asyncio
@respx.mock
async def test_check_down_500() -> None:
    respx.get("https://example.com").mock(return_value=httpx.Response(500))
    result = await perform_check(
        monitor_id="test-monitor",
        url="https://example.com",
        timeout_seconds=10,
        follow_redirects=True,
        expected_status_codes=[200],
        ssl_check_enabled=False,
    )
    assert result.status == "down"
    assert result.http_status == 500


@pytest.mark.asyncio
@respx.mock
async def test_check_redirect_followed() -> None:
    respx.get("http://example.com").mock(
        return_value=httpx.Response(301, headers={"Location": "https://example.com"})
    )
    respx.get("https://example.com").mock(return_value=httpx.Response(200))
    result = await perform_check(
        monitor_id="redirect-monitor",
        url="http://example.com",
        timeout_seconds=10,
        follow_redirects=True,
        expected_status_codes=[200],
        ssl_check_enabled=False,
    )
    assert result.status == "up"
    assert result.redirect_count >= 1


@pytest.mark.asyncio
@respx.mock
async def test_check_timeout() -> None:
    respx.get("https://example.com").mock(side_effect=httpx.TimeoutException("timeout"))
    result = await perform_check(
        monitor_id="timeout-monitor",
        url="https://example.com",
        timeout_seconds=1,
        follow_redirects=True,
        expected_status_codes=[200],
        ssl_check_enabled=False,
    )
    assert result.status == "timeout"
    assert result.error_message is not None


@pytest.mark.asyncio
@respx.mock
async def test_check_connection_error() -> None:
    respx.get("https://unreachable.example").mock(side_effect=httpx.ConnectError("refused"))
    result = await perform_check(
        monitor_id="error-monitor",
        url="https://unreachable.example",
        timeout_seconds=5,
        follow_redirects=True,
        expected_status_codes=[200],
        ssl_check_enabled=False,
    )
    assert result.status == "error"
    assert "Connection error" in (result.error_message or "")


@pytest.mark.asyncio
@respx.mock
async def test_result_to_dict() -> None:
    respx.get("https://example.com").mock(return_value=httpx.Response(200))
    result = await perform_check(
        monitor_id="dict-test",
        url="https://example.com",
        timeout_seconds=10,
        follow_redirects=True,
        expected_status_codes=[200],
        ssl_check_enabled=False,
    )
    d = result.to_dict()
    assert d["monitor_id"] == "dict-test"
    assert d["status"] == "up"
    assert "checked_at" in d
