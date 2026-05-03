"""Tests for T2-05 SSL pinning + chain expiry enforcement in HTTPChecker."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx

from whatisup_probe.checkers import perform_check


@pytest.mark.asyncio
@respx.mock
async def test_ssl_pin_match_keeps_status_up() -> None:
    """When the served SHA-256 matches the configured pin, status stays 'up'."""
    respx.get("https://pinned.example/").mock(return_value=httpx.Response(200, text="ok"))
    pin = "a" * 64

    with patch(
        "whatisup_probe.checkers.http.extract_ssl_info",
        new=AsyncMock(return_value=(True, datetime.now(UTC), 90, pin)),
    ):
        result = await perform_check(
            monitor_id="m1",
            url="https://pinned.example/",
            timeout_seconds=5,
            follow_redirects=True,
            expected_status_codes=[200],
            ssl_check_enabled=True,
            ssl_pin_sha256=pin,
        )

    assert result.status == "up"
    assert result.ssl_valid is True
    assert result.error_message is None


@pytest.mark.asyncio
@respx.mock
async def test_ssl_pin_mismatch_marks_down() -> None:
    """A served cert with a different SHA-256 must flip the check to 'down'."""
    respx.get("https://pinned.example/").mock(return_value=httpx.Response(200, text="ok"))
    served = "b" * 64
    expected = "a" * 64

    with patch(
        "whatisup_probe.checkers.http.extract_ssl_info",
        new=AsyncMock(return_value=(True, datetime.now(UTC), 90, served)),
    ):
        result = await perform_check(
            monitor_id="m1",
            url="https://pinned.example/",
            timeout_seconds=5,
            follow_redirects=True,
            expected_status_codes=[200],
            ssl_check_enabled=True,
            ssl_pin_sha256=expected,
        )

    assert result.status == "down"
    assert "ssl_pin_mismatch" in (result.error_message or "")
    assert result.ssl_valid is False


@pytest.mark.asyncio
@respx.mock
async def test_ssl_min_chain_days_enforced() -> None:
    """If the leaf has fewer days remaining than the minimum, status flips down."""
    respx.get("https://soon.example/").mock(return_value=httpx.Response(200, text="ok"))

    with patch(
        "whatisup_probe.checkers.http.extract_ssl_info",
        new=AsyncMock(return_value=(True, datetime.now(UTC), 5, "c" * 64)),
    ):
        result = await perform_check(
            monitor_id="m1",
            url="https://soon.example/",
            timeout_seconds=5,
            follow_redirects=True,
            expected_status_codes=[200],
            ssl_check_enabled=True,
            ssl_min_chain_days=15,
        )

    assert result.status == "down"
    assert "ssl_chain_expiring" in (result.error_message or "")


@pytest.mark.asyncio
@respx.mock
async def test_ssl_min_chain_days_passes_when_enough() -> None:
    """No flip when the chain has more days than the minimum."""
    respx.get("https://safe.example/").mock(return_value=httpx.Response(200, text="ok"))

    with patch(
        "whatisup_probe.checkers.http.extract_ssl_info",
        new=AsyncMock(return_value=(True, datetime.now(UTC), 90, "d" * 64)),
    ):
        result = await perform_check(
            monitor_id="m1",
            url="https://safe.example/",
            timeout_seconds=5,
            follow_redirects=True,
            expected_status_codes=[200],
            ssl_check_enabled=True,
            ssl_min_chain_days=15,
        )

    assert result.status == "up"
    assert result.error_message is None


@pytest.mark.asyncio
@respx.mock
async def test_ssl_pin_ignored_when_check_disabled() -> None:
    """ssl_check_enabled=False short-circuits all SSL logic, including pinning."""
    respx.get("https://pinned.example/").mock(return_value=httpx.Response(200, text="ok"))

    with patch(
        "whatisup_probe.checkers.http.extract_ssl_info",
        new=AsyncMock(return_value=(True, None, None, "e" * 64)),
    ) as mock_ssl:
        result = await perform_check(
            monitor_id="m1",
            url="https://pinned.example/",
            timeout_seconds=5,
            follow_redirects=True,
            expected_status_codes=[200],
            ssl_check_enabled=False,
            ssl_pin_sha256="f" * 64,
        )

    assert result.status == "up"
    # SSL extraction must not be called at all when disabled.
    assert mock_ssl.await_count == 0
