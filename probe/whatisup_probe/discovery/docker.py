"""Docker discovery source — read-only container/port inventory (plan D, D-1).

Talks to the Docker Engine API over its Unix socket via ``httpx`` — no docker
SDK dependency, no privileged mode: a plain HTTP GET against a socket that is
expected to be mounted ``:ro`` (plan_discovery.md § Sécurité). The socket is
absent from the compose file by default; an operator opts in explicitly.
"""

from __future__ import annotations

import os
import stat
from typing import Any

import httpx
import structlog

from whatisup_probe.config import get_settings

from .base import BaseDiscoverySource, DiscoveredItem

logger = structlog.get_logger(__name__)

#: Docker labels never leave the probe if their key contains one of these
#: substrings (case-insensitive) — a label is operator-controlled metadata,
#: and nothing stops someone from stuffing a credential into one.
_SENSITIVE_LABEL_SUBSTRINGS = ("secret", "token", "password", "key")
_MAX_LABELS = 16
_LABEL_TRUNC = 128

_DOCKER_API_TIMEOUT = 5.0


def _filter_labels(labels: dict[str, Any] | None) -> dict[str, str]:
    """Bound + redact container labels before they ever leave the probe.

    Never env vars (Docker's `/containers/json` doesn't return them anyway —
    this filters what it *does* return): capped count, capped length, and
    any label whose key smells like a secret is dropped outright rather than
    truncated (a truncated secret is still a leaked secret).
    """
    if not labels:
        return {}
    out: dict[str, str] = {}
    for key, value in labels.items():
        if len(out) >= _MAX_LABELS:
            break
        key_lower = str(key).lower()
        if any(marker in key_lower for marker in _SENSITIVE_LABEL_SUBSTRINGS):
            continue
        out[str(key)[:_LABEL_TRUNC]] = str(value)[:_LABEL_TRUNC]
    return out


class DockerDiscoverySource(BaseDiscoverySource):
    source_type = "docker"

    def _transport(self) -> httpx.AsyncHTTPTransport:
        return httpx.AsyncHTTPTransport(uds=get_settings().discovery_docker_socket)

    async def capability_available(self) -> bool:
        """Socket present, is actually a socket, and readable/writable by us.

        A plain filesystem check rather than an API round-trip: cheap, and
        it's exactly what "the socket is mounted and accessible" means —
        matches the docstring in ``docker-compose.yml``'s opt-in comment.
        """
        socket_path = get_settings().discovery_docker_socket
        try:
            st = os.stat(socket_path)
        except OSError:
            return False
        if not stat.S_ISSOCK(st.st_mode):
            return False
        return os.access(socket_path, os.R_OK | os.W_OK)

    async def run(self, params: dict[str, Any]) -> list[DiscoveredItem]:
        items: list[DiscoveredItem] = []
        try:
            async with httpx.AsyncClient(
                transport=self._transport(), timeout=_DOCKER_API_TIMEOUT
            ) as client:
                resp = await client.get(
                    "http://docker/containers/json",
                    params={"filters": '{"status":["running"]}'},
                )
                resp.raise_for_status()
                containers = resp.json()
        except Exception as exc:  # noqa: BLE001 — a broken source must not crash the loop
            logger.warning("discovery_docker_run_failed", error=str(exc))
            return []

        for container in containers:
            image = str(container.get("Image", ""))
            names = container.get("Names") or []
            container_name = names[0].lstrip("/") if names else ""
            labels = _filter_labels(container.get("Labels"))
            hints = {"image": image, "container_name": container_name, "labels": labels}

            for port_entry in container.get("Ports", []) or []:
                public_port = port_entry.get("PublicPort")
                if not public_port:
                    continue  # container-only port, never published to the host
                # "0.0.0.0"/"::" binds mean "every interface" — not a useful
                # target host, fall back to loopback (the probe and the
                # docker daemon share the same host in the supported setup).
                bound_ip = port_entry.get("IP")
                host = bound_ip if bound_ip and bound_ip not in ("0.0.0.0", "::") else "127.0.0.1"
                proto = port_entry.get("Type", "tcp")
                items.append(
                    DiscoveredItem(host=host, port=int(public_port), proto=proto, hints=hints)
                )

        return items


def setup(register: Any) -> None:
    register(DockerDiscoverySource())
