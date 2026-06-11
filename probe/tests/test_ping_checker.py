"""Tests for the ICMP ping checker (subprocess mocked, no real network)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from whatisup_probe.checkers.ping import PingChecker

_PING_OK_OUTPUT = (
    b"PING example.com (93.184.216.34) 56(84) bytes of data.\n"
    b"64 bytes from 93.184.216.34: icmp_seq=1 ttl=56 time=12.3 ms\n"
    b"\n--- example.com ping statistics ---\n"
    b"1 packets transmitted, 1 received, 0% packet loss, time 0ms\n"
)


def _config(**overrides: Any) -> dict[str, Any]:
    config: dict[str, Any] = {"url": "https://example.com", "timeout_seconds": 5}
    config.update(overrides)
    return config


def _fake_proc(returncode: int = 0, stdout: bytes = b"") -> MagicMock:
    proc = MagicMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=(stdout, b""))
    return proc


def _patch_subprocess(monkeypatch, proc: MagicMock) -> AsyncMock:
    exec_mock = AsyncMock(return_value=proc)
    monkeypatch.setattr("whatisup_probe.checkers.ping.asyncio.create_subprocess_exec", exec_mock)
    return exec_mock


@pytest.mark.asyncio
async def test_ping_up_parses_rtt_from_output(monkeypatch) -> None:
    """A successful ping reports the RTT parsed from the ping output."""
    _patch_subprocess(monkeypatch, _fake_proc(returncode=0, stdout=_PING_OK_OUTPUT))

    result = await PingChecker().check("ping-up", _config())

    assert result.status == "up"
    assert result.response_time_ms == 12.3
    assert result.error_message is None


@pytest.mark.asyncio
async def test_ping_up_falls_back_to_elapsed_time(monkeypatch) -> None:
    """When no time= is found in the output, elapsed wall time is used."""
    _patch_subprocess(monkeypatch, _fake_proc(returncode=0, stdout=b"no rtt here"))

    result = await PingChecker().check("ping-no-rtt", _config())

    assert result.status == "up"
    assert result.response_time_ms is not None
    assert result.response_time_ms >= 0


@pytest.mark.asyncio
async def test_ping_down_on_nonzero_exit(monkeypatch) -> None:
    _patch_subprocess(monkeypatch, _fake_proc(returncode=1, stdout=b""))

    result = await PingChecker().check("ping-down", _config())

    assert result.status == "down"
    assert "Ping failed: host unreachable" in (result.error_message or "")
    assert result.response_time_ms is not None


@pytest.mark.asyncio
async def test_ping_timeout(monkeypatch) -> None:
    proc = _fake_proc()
    proc.communicate = AsyncMock(side_effect=TimeoutError)
    _patch_subprocess(monkeypatch, proc)

    result = await PingChecker().check("ping-timeout", _config())

    assert result.status == "timeout"
    assert "Ping timeout after 5s" in (result.error_message or "")


@pytest.mark.asyncio
async def test_ping_binary_not_found(monkeypatch) -> None:
    exec_mock = AsyncMock(side_effect=FileNotFoundError)
    monkeypatch.setattr("whatisup_probe.checkers.ping.asyncio.create_subprocess_exec", exec_mock)

    result = await PingChecker().check("ping-nobin", _config())

    assert result.status == "error"
    assert result.error_message == "ping binary not found"


@pytest.mark.asyncio
async def test_ping_rejects_unsafe_host(monkeypatch) -> None:
    """Hosts failing the safe-host regex are rejected before any subprocess spawn."""
    exec_mock = AsyncMock()
    monkeypatch.setattr("whatisup_probe.checkers.ping.asyncio.create_subprocess_exec", exec_mock)

    result = await PingChecker().check("ping-inject", _config(url="evil; rm -rf /"))

    assert result.status == "error"
    assert result.error_message == "Invalid host for ping check"
    exec_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_ping_command_arguments(monkeypatch) -> None:
    """The ping command uses one packet, the configured timeout and the parsed host."""
    exec_mock = _patch_subprocess(monkeypatch, _fake_proc(returncode=0, stdout=_PING_OK_OUTPUT))

    await PingChecker().check("ping-args", _config())

    args = exec_mock.await_args.args
    assert args == ("ping", "-c", "1", "-W", "5", "example.com")
