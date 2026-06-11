"""Tests for the SMTP server checker (asyncio streams mocked, no real network)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from whatisup_probe.checkers.smtp import SMTPChecker


@pytest.fixture(autouse=True)
def _allow_hosts(monkeypatch):
    """Bypass SSRF host validation (fake hostnames won't resolve in tests)."""
    monkeypatch.setattr("whatisup_probe.checkers.smtp.validate_host_ssrf", lambda host: None)


def _config(**overrides: Any) -> dict[str, Any]:
    config: dict[str, Any] = {"url": "smtp://mail.example.com", "timeout_seconds": 5}
    config.update(overrides)
    return config


def _fake_streams(lines: list[bytes]) -> tuple[MagicMock, MagicMock]:
    """Build a (reader, writer) pair; the reader replays *lines* in order."""
    reader = MagicMock()
    reader.readline = AsyncMock(side_effect=lines)
    writer = MagicMock()
    writer.drain = AsyncMock()
    writer.wait_closed = AsyncMock()
    return reader, writer


def _patch_connection(monkeypatch, lines: list[bytes]) -> tuple[AsyncMock, MagicMock]:
    reader, writer = _fake_streams(lines)
    open_conn = AsyncMock(return_value=(reader, writer))
    monkeypatch.setattr("whatisup_probe.checkers.smtp.asyncio.open_connection", open_conn)
    return open_conn, writer


def _written(writer: MagicMock) -> list[bytes]:
    return [call.args[0] for call in writer.write.call_args_list]


@pytest.mark.asyncio
async def test_smtp_up_full_dialogue(monkeypatch) -> None:
    """Banner 220 + multi-line EHLO reply ends with QUIT and status=up."""
    _, writer = _patch_connection(
        monkeypatch,
        [
            b"220 mail.example.com ESMTP ready\r\n",
            b"250-PIPELINING\r\n",
            b"250 OK\r\n",
        ],
    )

    result = await SMTPChecker().check("smtp-up", _config())

    assert result.status == "up"
    assert result.error_message is None
    assert result.response_time_ms is not None
    assert b"EHLO whatisup-monitor\r\n" in _written(writer)
    assert b"QUIT\r\n" in _written(writer)
    writer.close.assert_called_once()


@pytest.mark.asyncio
async def test_smtp_down_on_bad_banner(monkeypatch) -> None:
    _, writer = _patch_connection(monkeypatch, [b"554 No SMTP service here\r\n"])

    result = await SMTPChecker().check("smtp-banner", _config())

    assert result.status == "down"
    assert "Unexpected SMTP banner: 554 No SMTP service here" in (result.error_message or "")
    writer.close.assert_called_once()


@pytest.mark.asyncio
async def test_smtp_starttls_accepted(monkeypatch) -> None:
    """With smtp_starttls=True, a 220 STARTTLS reply keeps the check up."""
    _, writer = _patch_connection(
        monkeypatch,
        [
            b"220 mail.example.com ESMTP\r\n",
            b"250 STARTTLS\r\n",
            b"220 2.0.0 Ready to start TLS\r\n",
        ],
    )

    result = await SMTPChecker().check("smtp-tls", _config(smtp_starttls=True))

    assert result.status == "up"
    assert b"STARTTLS\r\n" in _written(writer)


@pytest.mark.asyncio
async def test_smtp_starttls_rejected(monkeypatch) -> None:
    _, _ = _patch_connection(
        monkeypatch,
        [
            b"220 mail.example.com ESMTP\r\n",
            b"250 OK\r\n",
            b"502 STARTTLS not implemented\r\n",
        ],
    )

    result = await SMTPChecker().check("smtp-tls-no", _config(smtp_starttls=True))

    assert result.status == "down"
    assert "STARTTLS rejected: 502" in (result.error_message or "")


@pytest.mark.asyncio
async def test_smtp_connection_refused(monkeypatch) -> None:
    open_conn = AsyncMock(side_effect=ConnectionRefusedError("connection refused"))
    monkeypatch.setattr("whatisup_probe.checkers.smtp.asyncio.open_connection", open_conn)

    result = await SMTPChecker().check("smtp-refused", _config())

    assert result.status == "down"
    assert "SMTP connection refused" in (result.error_message or "")


@pytest.mark.asyncio
async def test_smtp_timeout(monkeypatch) -> None:
    open_conn = AsyncMock(side_effect=TimeoutError)
    monkeypatch.setattr("whatisup_probe.checkers.smtp.asyncio.open_connection", open_conn)

    result = await SMTPChecker().check("smtp-timeout", _config())

    assert result.status == "timeout"
    assert "SMTP timeout after 5s" in (result.error_message or "")


@pytest.mark.asyncio
async def test_smtp_default_port_25(monkeypatch) -> None:
    open_conn, _ = _patch_connection(
        monkeypatch,
        [b"220 hi\r\n", b"250 OK\r\n"],
    )

    await SMTPChecker().check("smtp-port-default", _config())

    open_conn.assert_awaited_once_with("mail.example.com", 25)


@pytest.mark.asyncio
async def test_smtp_port_from_config(monkeypatch) -> None:
    open_conn, _ = _patch_connection(
        monkeypatch,
        [b"220 hi\r\n", b"250 OK\r\n"],
    )

    await SMTPChecker().check("smtp-port", _config(smtp_port=587))

    open_conn.assert_awaited_once_with("mail.example.com", 587)


@pytest.mark.asyncio
async def test_smtp_ssrf_blocked(monkeypatch) -> None:
    monkeypatch.setattr(
        "whatisup_probe.checkers.smtp.validate_host_ssrf",
        lambda host: f"Blocked host: {host!r}",
    )
    open_conn = AsyncMock()
    monkeypatch.setattr("whatisup_probe.checkers.smtp.asyncio.open_connection", open_conn)

    result = await SMTPChecker().check("smtp-ssrf", _config(url="smtp://localhost"))

    assert result.status == "error"
    assert "SSRF blocked" in (result.error_message or "")
    open_conn.assert_not_awaited()
