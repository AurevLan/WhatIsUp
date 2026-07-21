"""Tests for the SSRF IP-pinning transport (server SA1 pattern ported to the probe).

This module is excluded from the conftest ``_bypass_ssrf_pinning`` fixture so
the real ``_ssrf_resolve_pinned_sync`` logic runs; DNS is stubbed via
``_cached_getaddrinfo``.
"""

from __future__ import annotations

import socket

import httpx
import pytest

from whatisup_probe.checkers import _shared, perform_check
from whatisup_probe.checkers._shared import (
    SSRFBlockedError,
    _ssrf_resolve_pinned_sync,
    _SSRFPinnedTransport,
)

PUBLIC_IP = "93.184.216.34"


def _addrinfo(ip: str) -> list:
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))]


class _CaptureTransport(httpx.AsyncBaseTransport):
    """Inner transport stub capturing each request as the wire would see it."""

    def __init__(self, responses: list[tuple[int, dict]]) -> None:
        self.seen: list[dict] = []
        self._responses = list(responses)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.seen.append(
            {
                "url": str(request.url),
                "host_header": request.headers.get("host"),
                "sni": request.extensions.get("sni_hostname"),
            }
        )
        status, headers = self._responses.pop(0)
        return httpx.Response(status, headers=headers, request=request)


# ── _ssrf_resolve_pinned_sync ────────────────────────────────────────────────


def test_resolve_blocks_blocked_host():
    with pytest.raises(SSRFBlockedError, match="Blocked host"):
        _ssrf_resolve_pinned_sync("metadata.google.internal")


def test_resolve_blocks_internal_ip_literal():
    with pytest.raises(SSRFBlockedError, match="internal IP"):
        _ssrf_resolve_pinned_sync("10.0.0.5")


def test_resolve_passes_public_ip_literal_unchanged():
    assert _ssrf_resolve_pinned_sync(PUBLIC_IP) == PUBLIC_IP


def test_resolve_blocks_hostname_resolving_internal(monkeypatch):
    monkeypatch.setattr(_shared, "_cached_getaddrinfo", lambda h, *a, **k: _addrinfo("192.168.1.1"))
    with pytest.raises(SSRFBlockedError, match="resolves to internal IP"):
        _ssrf_resolve_pinned_sync("evil.example.com")


def test_resolve_returns_pinned_public_ip(monkeypatch):
    monkeypatch.setattr(_shared, "_cached_getaddrinfo", lambda h, *a, **k: _addrinfo(PUBLIC_IP))
    assert _ssrf_resolve_pinned_sync("example.com") == PUBLIC_IP


def test_resolve_dns_failure_blocked(monkeypatch):
    def boom(h, *a, **k):
        raise socket.gaierror("NXDOMAIN")

    monkeypatch.setattr(_shared, "_cached_getaddrinfo", boom)
    with pytest.raises(SSRFBlockedError, match="DNS resolution failed"):
        _ssrf_resolve_pinned_sync("nope.example.com")


# ── _SSRFPinnedTransport ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_transport_pins_ip_preserves_host_header_and_sni(monkeypatch):
    monkeypatch.setattr(_shared, "_cached_getaddrinfo", lambda h, *a, **k: _addrinfo(PUBLIC_IP))
    inner = _CaptureTransport([(200, {})])
    async with httpx.AsyncClient(transport=_SSRFPinnedTransport(inner=inner)) as client:
        resp = await client.get("https://example.com/ping")

    wire = inner.seen[0]
    assert wire["url"] == f"https://{PUBLIC_IP}/ping"
    assert wire["host_header"] == "example.com"
    assert wire["sni"] == "example.com"
    # URL restored after the call — reporting keeps the real hostname.
    assert resp.request.url.host == "example.com"


@pytest.mark.asyncio
async def test_transport_blocks_internal_resolution(monkeypatch):
    """Rebinding scenario: connect-time resolution lands on an internal IP."""
    monkeypatch.setattr(_shared, "_cached_getaddrinfo", lambda h, *a, **k: _addrinfo("10.0.0.5"))
    inner = _CaptureTransport([(200, {})])
    async with httpx.AsyncClient(transport=_SSRFPinnedTransport(inner=inner)) as client:
        with pytest.raises(SSRFBlockedError):
            await client.get("https://rebind.example.com/")
    assert inner.seen == []  # never reached the wire


@pytest.mark.asyncio
async def test_redirect_hop_to_internal_blocked(monkeypatch):
    """https://public → 302 → cloud metadata: the hop is validated and blocked."""
    monkeypatch.setattr(_shared, "_cached_getaddrinfo", lambda h, *a, **k: _addrinfo(PUBLIC_IP))
    inner = _CaptureTransport([(302, {"location": "http://169.254.169.254/latest/meta-data/"})])
    async with httpx.AsyncClient(
        transport=_SSRFPinnedTransport(inner=inner), follow_redirects=True
    ) as client:
        with pytest.raises(SSRFBlockedError):
            await client.get("https://example.com/")
    assert len(inner.seen) == 1  # only the first hop hit the wire


@pytest.mark.asyncio
async def test_relative_redirect_keeps_hostname(monkeypatch):
    """URL restore: relative Location resolves against the hostname, not the IP."""
    monkeypatch.setattr(_shared, "_cached_getaddrinfo", lambda h, *a, **k: _addrinfo(PUBLIC_IP))
    inner = _CaptureTransport([(302, {"location": "/next"}), (200, {})])
    async with httpx.AsyncClient(
        transport=_SSRFPinnedTransport(inner=inner), follow_redirects=True
    ) as client:
        resp = await client.get("https://example.com/start")

    assert [s["url"] for s in inner.seen] == [
        f"https://{PUBLIC_IP}/start",
        f"https://{PUBLIC_IP}/next",
    ]
    assert all(s["host_header"] == "example.com" for s in inner.seen)
    assert str(resp.url) == "https://example.com/next"


# ── Checker integration ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_http_checker_reports_rebinding_as_ssrf_blocked(monkeypatch):
    """Resolution flips public → internal between pre-check and connect: the
    pinning transport catches it and the checker reports an SSRF error."""
    calls = {"n": 0}

    def flip(h, *a, **k):
        calls["n"] += 1
        return _addrinfo(PUBLIC_IP if calls["n"] == 1 else "10.0.0.5")

    monkeypatch.setattr(_shared, "_cached_getaddrinfo", flip)
    monkeypatch.setattr("whatisup_probe.checkers.http._cached_getaddrinfo", flip)
    # Fresh shared client so this test's transport resolution is exercised.
    monkeypatch.setattr(_shared, "_http_client", None)

    result = await perform_check(
        monitor_id="m-rebind",
        url="https://rebind.example.com/",
        timeout_seconds=5,
        follow_redirects=True,
        expected_status_codes=[200],
        ssl_check_enabled=False,
    )
    assert result.status == "error"
    assert "SSRF blocked" in (result.error_message or "")
