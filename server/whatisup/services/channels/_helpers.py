"""Shared helpers for alert channel plugins — SSRF validation, scope labels."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlparse

from whatisup.models.incident import Incident, IncidentScope


def _validate_webhook_url_sync(url: str) -> None:
    """Blocking SSRF check — meant to be called via run_in_executor."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Webhook URL scheme must be http or https, got: {parsed.scheme!r}")

    hostname = parsed.hostname
    if not hostname:
        raise ValueError("Webhook URL has no hostname")

    if hostname.lower() in {
        "localhost", "127.0.0.1", "::1", "0.0.0.0",
        "169.254.169.254", "metadata.google.internal",
    }:
        raise ValueError(f"Webhook URL points to blocked host: {hostname!r}")

    try:
        addr_infos = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
        for addr_info in addr_infos:
            resolved_ip = addr_info[4][0]
            ip = ipaddress.ip_address(resolved_ip)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast:
                raise ValueError(f"Webhook URL resolves to internal IP: {resolved_ip!r}")
    except socket.gaierror:
        raise ValueError(f"Webhook URL hostname cannot be resolved: {hostname!r}")


async def validate_webhook_url(url: str) -> None:
    """Reject webhook URLs pointing to internal/private IP ranges (SSRF prevention).

    DNS resolution runs in an executor to avoid blocking the event loop.
    """
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _validate_webhook_url_sync, url)


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
