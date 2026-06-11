"""Tests for the TCP port reachability checker."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from whatisup_probe.checkers.tcp import TCPChecker


@pytest.fixture(autouse=True)
def _allow_hosts(monkeypatch):
    """Bypass SSRF host validation (fake hostnames won't resolve in tests)."""
    monkeypatch.setattr("whatisup_probe.checkers.tcp.validate_host_ssrf", lambda host: None)


def _config(**overrides: Any) -> dict[str, Any]:
    config: dict[str, Any] = {"url": "tcp://example.com:5432", "timeout_seconds": 5}
    config.update(overrides)
    return config


def _fake_streams() -> tuple[MagicMock, MagicMock]:
    reader = MagicMock()
    writer = MagicMock()
    writer.wait_closed = AsyncMock()
    return reader, writer


@pytest.mark.asyncio
async def test_tcp_up(monkeypatch) -> None:
    """A successful connection yields status=up with a measured response time."""
    open_conn = AsyncMock(return_value=_fake_streams())
    monkeypatch.setattr("whatisup_probe.checkers.tcp.asyncio.open_connection", open_conn)

    result = await TCPChecker().check("tcp-up", _config())

    assert result.status == "up"
    assert result.error_message is None
    assert result.response_time_ms is not None
    assert result.response_time_ms >= 0


@pytest.mark.asyncio
async def test_tcp_closes_connection_on_success(monkeypatch) -> None:
    """The checker must close the writer after a successful probe."""
    reader, writer = _fake_streams()
    open_conn = AsyncMock(return_value=(reader, writer))
    monkeypatch.setattr("whatisup_probe.checkers.tcp.asyncio.open_connection", open_conn)

    await TCPChecker().check("tcp-close", _config())

    writer.close.assert_called_once()
    writer.wait_closed.assert_awaited_once()


@pytest.mark.asyncio
async def test_tcp_port_from_config_overrides_url(monkeypatch) -> None:
    """An explicit tcp_port takes precedence over the port embedded in the URL."""
    open_conn = AsyncMock(return_value=_fake_streams())
    monkeypatch.setattr("whatisup_probe.checkers.tcp.asyncio.open_connection", open_conn)

    await TCPChecker().check("tcp-port", _config(tcp_port=8443))

    open_conn.assert_awaited_once_with("example.com", 8443)


@pytest.mark.asyncio
async def test_tcp_port_parsed_from_url(monkeypatch) -> None:
    """Without tcp_port, the port comes from the URL (here 5432)."""
    open_conn = AsyncMock(return_value=_fake_streams())
    monkeypatch.setattr("whatisup_probe.checkers.tcp.asyncio.open_connection", open_conn)

    await TCPChecker().check("tcp-url-port", _config())

    open_conn.assert_awaited_once_with("example.com", 5432)


@pytest.mark.asyncio
async def test_tcp_timeout(monkeypatch) -> None:
    open_conn = AsyncMock(side_effect=TimeoutError)
    monkeypatch.setattr("whatisup_probe.checkers.tcp.asyncio.open_connection", open_conn)

    result = await TCPChecker().check("tcp-timeout", _config())

    assert result.status == "timeout"
    assert "TCP timeout after 5s" in (result.error_message or "")
    assert result.response_time_ms is not None


@pytest.mark.asyncio
async def test_tcp_connection_refused(monkeypatch) -> None:
    open_conn = AsyncMock(side_effect=ConnectionRefusedError("connection refused"))
    monkeypatch.setattr("whatisup_probe.checkers.tcp.asyncio.open_connection", open_conn)

    result = await TCPChecker().check("tcp-refused", _config())

    assert result.status == "down"
    assert "TCP connection refused" in (result.error_message or "")


@pytest.mark.asyncio
async def test_tcp_unexpected_error(monkeypatch) -> None:
    """Non-OSError exceptions map to status=error with the exception type in the message."""
    open_conn = AsyncMock(side_effect=ValueError("boom"))
    monkeypatch.setattr("whatisup_probe.checkers.tcp.asyncio.open_connection", open_conn)

    result = await TCPChecker().check("tcp-error", _config())

    assert result.status == "error"
    assert "ValueError: boom" in (result.error_message or "")


@pytest.mark.asyncio
async def test_tcp_ssrf_blocked(monkeypatch) -> None:
    """An SSRF-blocked host short-circuits the check before any connection attempt."""
    monkeypatch.setattr(
        "whatisup_probe.checkers.tcp.validate_host_ssrf",
        lambda host: f"Blocked host: {host!r}",
    )
    open_conn = AsyncMock()
    monkeypatch.setattr("whatisup_probe.checkers.tcp.asyncio.open_connection", open_conn)

    result = await TCPChecker().check("tcp-ssrf", _config(url="tcp://localhost:5432"))

    assert result.status == "error"
    assert "SSRF blocked" in (result.error_message or "")
    open_conn.assert_not_awaited()
