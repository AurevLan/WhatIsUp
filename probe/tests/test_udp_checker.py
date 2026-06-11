"""Tests for the UDP port checker (socket-level mocking, no real network)."""

from __future__ import annotations

import socket as socket_module
from typing import Any
from unittest.mock import MagicMock

import pytest

from whatisup_probe.checkers.udp import UDPChecker


@pytest.fixture(autouse=True)
def _allow_hosts(monkeypatch):
    """Bypass SSRF host validation (fake hostnames won't resolve in tests)."""
    monkeypatch.setattr("whatisup_probe.checkers.udp.validate_host_ssrf", lambda host: None)


def _config(**overrides: Any) -> dict[str, Any]:
    config: dict[str, Any] = {"url": "udp://example.com:9999", "timeout_seconds": 5}
    config.update(overrides)
    return config


def _patch_socket(monkeypatch) -> MagicMock:
    """Replace socket.socket with a factory returning a single fake socket."""
    sock = MagicMock()
    sock.recv.return_value = b"pong"
    monkeypatch.setattr(socket_module, "socket", lambda *a, **k: sock)
    return sock


@pytest.mark.asyncio
async def test_udp_up_with_response(monkeypatch) -> None:
    """A datagram answer means the port is up."""
    sock = _patch_socket(monkeypatch)

    result = await UDPChecker().check("udp-up", _config())

    assert result.status == "up"
    assert result.error_message is None
    assert result.response_time_ms is not None
    assert result.response_time_ms >= 0
    sock.close.assert_called_once()


@pytest.mark.asyncio
async def test_udp_up_when_no_response(monkeypatch) -> None:
    """No answer (recv timeout) is still up: UDP open|filtered semantics."""
    sock = _patch_socket(monkeypatch)
    sock.recv.side_effect = TimeoutError

    result = await UDPChecker().check("udp-silent", _config())

    assert result.status == "up"
    assert result.error_message is None


@pytest.mark.asyncio
async def test_udp_down_on_icmp_port_unreachable(monkeypatch) -> None:
    """ICMP port unreachable surfaces as ConnectionRefusedError → down."""
    sock = _patch_socket(monkeypatch)
    sock.recv.side_effect = ConnectionRefusedError

    result = await UDPChecker().check("udp-down", _config())

    assert result.status == "down"
    assert "UDP port 9999 unreachable" in (result.error_message or "")


@pytest.mark.asyncio
async def test_udp_timeout_on_connect(monkeypatch) -> None:
    sock = _patch_socket(monkeypatch)
    sock.connect.side_effect = TimeoutError

    result = await UDPChecker().check("udp-timeout", _config())

    assert result.status == "timeout"
    assert "UDP timeout after 5s" in (result.error_message or "")


@pytest.mark.asyncio
async def test_udp_error_on_os_error(monkeypatch) -> None:
    sock = _patch_socket(monkeypatch)
    sock.connect.side_effect = OSError("Network is unreachable")

    result = await UDPChecker().check("udp-error", _config())

    assert result.status == "error"
    assert "Network is unreachable" in (result.error_message or "")
    sock.close.assert_called_once()


@pytest.mark.asyncio
async def test_udp_port_from_config_overrides_url(monkeypatch) -> None:
    """An explicit udp_port takes precedence over the port embedded in the URL."""
    sock = _patch_socket(monkeypatch)

    await UDPChecker().check("udp-port", _config(udp_port=514))

    sock.connect.assert_called_once_with(("example.com", 514))


@pytest.mark.asyncio
async def test_udp_ssrf_blocked(monkeypatch) -> None:
    """An SSRF-blocked host short-circuits the check before any socket is opened."""
    monkeypatch.setattr(
        "whatisup_probe.checkers.udp.validate_host_ssrf",
        lambda host: f"Blocked host: {host!r}",
    )
    sock = _patch_socket(monkeypatch)

    result = await UDPChecker().check("udp-ssrf", _config(url="udp://localhost:53"))

    assert result.status == "error"
    assert "SSRF blocked" in (result.error_message or "")
    sock.connect.assert_not_called()
