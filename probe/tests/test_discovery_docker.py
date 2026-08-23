"""Docker discovery source — capability check + container/port parsing (plan D, D-1)."""

from __future__ import annotations

import json
import os
import socket
from pathlib import Path

import httpx
import pytest

from whatisup_probe.discovery.docker import DockerDiscoverySource, _filter_labels

pytestmark = pytest.mark.asyncio


# ── capability_available ──────────────────────────────────────────────────────


async def test_capability_available_true_for_real_socket(tmp_path: Path, monkeypatch) -> None:
    socket_path = str(tmp_path / "docker.sock")
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(socket_path)
    try:
        monkeypatch.setattr(
            "whatisup_probe.discovery.docker.get_settings",
            lambda: type("S", (), {"discovery_docker_socket": socket_path})(),
        )
        source = DockerDiscoverySource()
        assert await source.capability_available() is True
    finally:
        srv.close()


async def test_capability_available_false_when_missing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "whatisup_probe.discovery.docker.get_settings",
        lambda: type("S", (), {"discovery_docker_socket": str(tmp_path / "nope.sock")})(),
    )
    source = DockerDiscoverySource()
    assert await source.capability_available() is False


async def test_capability_available_false_for_regular_file(tmp_path: Path, monkeypatch) -> None:
    plain_file = tmp_path / "not-a-socket"
    plain_file.write_text("hello")
    monkeypatch.setattr(
        "whatisup_probe.discovery.docker.get_settings",
        lambda: type("S", (), {"discovery_docker_socket": str(plain_file)})(),
    )
    source = DockerDiscoverySource()
    assert await source.capability_available() is False


async def test_capability_available_false_when_unreadable(tmp_path: Path, monkeypatch) -> None:
    socket_path = str(tmp_path / "docker.sock")
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(socket_path)
    try:
        os.chmod(socket_path, 0o000)
        # Root (common in CI containers) bypasses the permission bits entirely
        # — this assertion is only meaningful as a non-root user.
        if os.geteuid() == 0:
            pytest.skip("running as root — permission bits are not enforced")
        monkeypatch.setattr(
            "whatisup_probe.discovery.docker.get_settings",
            lambda: type("S", (), {"discovery_docker_socket": socket_path})(),
        )
        source = DockerDiscoverySource()
        assert await source.capability_available() is False
    finally:
        # Owner rw is enough for tmp_path cleanup to unlink the socket.
        os.chmod(socket_path, 0o600)
        srv.close()


# ── label filtering ───────────────────────────────────────────────────────────


def test_filter_labels_drops_sensitive_keys() -> None:
    labels = {
        "com.example.role": "web",
        "API_TOKEN": "abc123",
        "db_password": "hunter2",
        "some.secret.value": "x",
        "my-key-thing": "y",
    }
    out = _filter_labels(labels)
    assert out == {"com.example.role": "web"}


def test_filter_labels_caps_count_and_length() -> None:
    labels = {f"label-{i}": "v" * 200 for i in range(30)}
    out = _filter_labels(labels)
    assert len(out) == 16
    assert all(len(v) == 128 for v in out.values())
    assert all(len(k) <= 128 for k in out)


def test_filter_labels_none_and_empty() -> None:
    assert _filter_labels(None) == {}
    assert _filter_labels({}) == {}


# ── run() — container/port parsing ────────────────────────────────────────────


def _mock_transport(containers: list[dict]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/containers/json"
        return httpx.Response(200, json=containers)

    return httpx.MockTransport(handler)


async def test_run_parses_published_ports(monkeypatch) -> None:
    containers = [
        {
            "Image": "nginx:latest",
            "Names": ["/my-nginx"],
            "Labels": {"com.example.role": "web"},
            "Ports": [
                {"IP": "0.0.0.0", "PrivatePort": 80, "PublicPort": 8080, "Type": "tcp"},
                {"PrivatePort": 443},  # not published — no PublicPort
            ],
        }
    ]
    source = DockerDiscoverySource()
    monkeypatch.setattr(source, "_transport", lambda: _mock_transport(containers))

    items = await source.run({})
    assert len(items) == 1
    item = items[0]
    assert item.host == "127.0.0.1"  # 0.0.0.0 binding falls back to loopback
    assert item.port == 8080
    assert item.proto == "tcp"
    assert item.hints["image"] == "nginx:latest"
    assert item.hints["container_name"] == "my-nginx"
    assert item.hints["labels"] == {"com.example.role": "web"}


async def test_run_keeps_specific_bound_ip(monkeypatch) -> None:
    containers = [
        {
            "Image": "redis",
            "Names": ["/redis-1"],
            "Labels": {},
            "Ports": [
                {"IP": "192.168.1.5", "PrivatePort": 6379, "PublicPort": 6379, "Type": "tcp"}
            ],
        }
    ]
    source = DockerDiscoverySource()
    monkeypatch.setattr(source, "_transport", lambda: _mock_transport(containers))

    items = await source.run({})
    assert items[0].host == "192.168.1.5"


async def test_run_no_running_containers_returns_empty(monkeypatch) -> None:
    source = DockerDiscoverySource()
    monkeypatch.setattr(source, "_transport", lambda: _mock_transport([]))
    assert await source.run({}) == []


async def test_run_socket_error_returns_empty_not_raises(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no such socket")

    source = DockerDiscoverySource()
    monkeypatch.setattr(source, "_transport", lambda: httpx.MockTransport(handler))

    assert await source.run({}) == []


async def test_run_udp_port_type_preserved(monkeypatch) -> None:
    containers = [
        {
            "Image": "coredns",
            "Names": ["/dns"],
            "Labels": {},
            "Ports": [{"IP": "0.0.0.0", "PrivatePort": 53, "PublicPort": 53, "Type": "udp"}],
        }
    ]
    source = DockerDiscoverySource()
    monkeypatch.setattr(source, "_transport", lambda: _mock_transport(containers))

    items = await source.run({})
    assert items[0].proto == "udp"


async def test_run_serializes_hints_json_safely(monkeypatch) -> None:
    """Regression guard: hints dict must survive a JSON round-trip (it's what
    gets pushed to POST /probes/discovery)."""
    containers = [
        {
            "Image": "nginx",
            "Names": ["/n"],
            "Labels": {"a": "b"},
            "Ports": [{"IP": "0.0.0.0", "PrivatePort": 80, "PublicPort": 80, "Type": "tcp"}],
        }
    ]
    source = DockerDiscoverySource()
    monkeypatch.setattr(source, "_transport", lambda: _mock_transport(containers))

    items = await source.run({})
    json.dumps(items[0].hints)  # must not raise
