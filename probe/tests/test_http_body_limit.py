"""Tests for the bounded HTTP body read (OOM protection) and liveness file."""

from __future__ import annotations

import httpx
import pytest
import respx

from whatisup_probe.checkers import perform_check
from whatisup_probe.scheduler import ProbeScheduler


@pytest.mark.asyncio
@respx.mock
async def test_large_body_does_not_fail_status_check(monkeypatch) -> None:
    """Without content checks, a huge body is truncated but the status verdict stands."""
    monkeypatch.setenv("HTTP_MAX_BODY_BYTES", "1024")
    respx.get("https://example.com").mock(return_value=httpx.Response(200, content=b"x" * 10_000))
    result = await perform_check(
        monitor_id="m-big",
        url="https://example.com",
        timeout_seconds=5,
        follow_redirects=True,
        expected_status_codes=[200],
        ssl_check_enabled=False,
    )
    assert result.status == "up"


@pytest.mark.asyncio
@respx.mock
async def test_truncated_body_with_keyword_check_errors(monkeypatch) -> None:
    """Keyword check on a truncated body → explicit error, not a false 'down'."""
    monkeypatch.setenv("HTTP_MAX_BODY_BYTES", "1024")
    respx.get("https://example.com").mock(
        return_value=httpx.Response(200, content=b"x" * 10_000 + b"NEEDLE")
    )
    result = await perform_check(
        monitor_id="m-trunc",
        url="https://example.com",
        timeout_seconds=5,
        follow_redirects=True,
        expected_status_codes=[200],
        ssl_check_enabled=False,
        check_type="keyword",
        keyword="NEEDLE",
    )
    assert result.status == "error"
    assert "exceeded" in (result.error_message or "")


@pytest.mark.asyncio
@respx.mock
async def test_small_body_keyword_check_unaffected() -> None:
    respx.get("https://example.com").mock(
        return_value=httpx.Response(200, content=b"hello NEEDLE world")
    )
    result = await perform_check(
        monitor_id="m-small",
        url="https://example.com",
        timeout_seconds=5,
        follow_redirects=True,
        expected_status_codes=[200],
        ssl_check_enabled=False,
        check_type="keyword",
        keyword="NEEDLE",
    )
    assert result.status == "up"


def test_touch_liveness_writes_file(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LIVENESS_FILE", str(tmp_path / "alive"))
    scheduler = ProbeScheduler()
    scheduler._touch_liveness()
    assert (tmp_path / "alive").exists()
