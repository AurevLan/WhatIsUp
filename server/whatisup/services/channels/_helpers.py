"""Shared helpers for alert channel plugins — SSRF validation, scope labels."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from typing import Any
from urllib.parse import urlparse

import httpx

from whatisup.models.incident import Incident, IncidentScope


def _validate_webhook_url_sync(url: str) -> str:
    """Blocking SSRF check — meant to be called via run_in_executor.

    Resolves DNS exactly once, validates *every* returned A/AAAA record, and
    returns the pinned IP (IPv4 preferred) that the caller must connect to.
    Connecting to the returned IP instead of re-resolving the hostname defeats
    DNS rebinding between validation and the actual request (SA1).
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Webhook URL scheme must be http or https, got: {parsed.scheme!r}")

    hostname = parsed.hostname
    if not hostname:
        raise ValueError("Webhook URL has no hostname")

    if hostname.lower() in {
        "localhost",
        "127.0.0.1",
        "::1",
        "0.0.0.0",
        "169.254.169.254",
        "metadata.google.internal",
    }:
        raise ValueError(f"Webhook URL points to blocked host: {hostname!r}")

    resolved_ips: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    try:
        addr_infos = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
        for addr_info in addr_infos:
            resolved_ip = addr_info[4][0]
            ip = ipaddress.ip_address(resolved_ip)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast:
                raise ValueError(f"Webhook URL resolves to internal IP: {resolved_ip!r}")
            resolved_ips.append(ip)
    except socket.gaierror:
        raise ValueError(f"Webhook URL hostname cannot be resolved: {hostname!r}")

    if not resolved_ips:
        raise ValueError(f"Webhook URL hostname cannot be resolved: {hostname!r}")

    # Pin: prefer IPv4 (most reachable), fall back to the first AAAA.
    for ip in resolved_ips:
        if ip.version == 4:
            return str(ip)
    return str(resolved_ips[0])


async def validate_webhook_url(url: str) -> str:
    """Reject webhook URLs pointing to internal/private IP ranges (SSRF prevention).

    Returns the validated (pinned) IP as a string. DNS resolution runs in an
    executor to avoid blocking the event loop.

    Note: fail-fast check only. The actual outbound request must go through
    :func:`ssrf_safe_client`, whose transport re-validates and *connects to*
    the pinned IP — this is what closes the DNS-rebinding window.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _validate_webhook_url_sync, url)


class _PinnedHostTransport(httpx.AsyncBaseTransport):
    """httpx transport enforcing SSRF validation + IP pinning per request.

    For every outgoing request: resolve the hostname once, reject if any
    resolved IP is private/loopback/link-local/multicast, then rewrite the URL
    host to the validated IP so httpx connects to it directly (no second DNS
    lookup → no rebinding window). The original hostname is preserved:
    - in the ``Host`` header (already built by httpx from the original URL),
    - as TLS server name via the ``sni_hostname`` request extension, so SNI
      and certificate hostname verification still target the real hostname.
    """

    def __init__(self, **kwargs: Any) -> None:
        self._inner = httpx.AsyncHTTPTransport(**kwargs)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        original_host = request.url.host
        loop = asyncio.get_running_loop()
        pinned_ip = await loop.run_in_executor(None, _validate_webhook_url_sync, str(request.url))
        if pinned_ip != original_host:
            # Host header was built from the original URL at request-creation
            # time and is left untouched — only the connection target changes.
            request.extensions = dict(request.extensions)
            request.extensions["sni_hostname"] = original_host
            request.url = request.url.copy_with(host=pinned_ip)
        return await self._inner.handle_async_request(request)

    async def aclose(self) -> None:
        await self._inner.aclose()


def ssrf_safe_client(timeout: float = 10) -> httpx.AsyncClient:
    """AsyncClient for user-supplied outbound URLs (webhooks, chat channels).

    Single DNS resolution at request time, private/internal IPs rejected, and
    the request is sent to the validated IP (anti DNS-rebinding). TLS keeps
    verifying the original hostname (SNI + cert check via ``sni_hostname``).
    """
    return httpx.AsyncClient(timeout=timeout, transport=_PinnedHostTransport())


# Values of these config keys must never appear in a log line, an API response
# or a stored alert event. `_SECRET_FIELDS` are Fernet-encrypted at rest;
# `webhook_url` is not (documented choice) but it is a bearer capability — a
# leaked Discord/Slack webhook URL is enough to post as the integration.
_REDACTED_CONFIG_KEYS = {
    "secret",
    "bot_token",
    "password",
    "integration_key",
    "api_key",
    "webhook_url",
}


def redact_secrets(text: str, config: dict[str, Any] | None) -> str:
    """Blank out any channel secret that leaked into an error string.

    httpx puts the request URL in `HTTPStatusError`, and providers like Telegram
    take their credential in the URL path, so `str(exc)` can carry a live token
    straight into the logs (audit F6). Channels should keep the secret out of
    the exception in the first place; this is the net under that.
    """
    if not text or not config:
        return text
    for key, value in config.items():
        if key in _REDACTED_CONFIG_KEYS and isinstance(value, str) and len(value) >= 8:
            text = text.replace(value, "***")
    return text


def scope_label_fr(incident: Incident, ctx: dict) -> str:
    """French scope label for notifications."""
    probe_names: dict = ctx.get("probe_names", {})
    affected = incident.affected_probe_ids or []

    if incident.scope == IncidentScope.global_:
        return "Panne globale (toutes les sondes)"

    if len(affected) == 1:
        name = probe_names.get(affected[0], affected[0])
        return f"Panne géographique — sonde : {name}"

    names = [probe_names.get(pid, pid) for pid in affected]
    return f"Panne géographique — sondes : {', '.join(names)}"


def scope_label_en(incident: Incident, ctx: dict) -> str:
    """English scope label for notifications."""
    probe_names: dict = ctx.get("probe_names", {})
    affected = incident.affected_probe_ids or []

    if incident.scope == IncidentScope.global_:
        return "Global outage (all probes)"

    if len(affected) == 1:
        name = probe_names.get(affected[0], affected[0])
        return f"Geographic outage — probe: {name}"

    names = [probe_names.get(pid, pid) for pid in affected]
    return f"Geographic outage — probes: {', '.join(names)}"
