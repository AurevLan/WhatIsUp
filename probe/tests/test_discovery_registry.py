"""Discovery source registry — completeness + capability report (plan D, D-1)."""

from __future__ import annotations

import pytest

from whatisup_probe.discovery import REGISTRY, capability_report, run_source
from whatisup_probe.discovery.base import BaseDiscoverySource
from whatisup_probe.discovery.docker import DockerDiscoverySource
from whatisup_probe.discovery.port_scan import PortScanDiscoverySource

pytestmark = pytest.mark.asyncio


def test_registry_contains_all_builtin_source_types() -> None:
    assert set(REGISTRY.keys()) == {"docker", "port_scan"}


def test_all_sources_inherit_from_base() -> None:
    for name, source in REGISTRY.items():
        assert isinstance(source, BaseDiscoverySource), (
            f"{name} does not inherit from BaseDiscoverySource"
        )


def test_registry_instances_are_the_expected_classes() -> None:
    assert isinstance(REGISTRY["docker"], DockerDiscoverySource)
    assert isinstance(REGISTRY["port_scan"], PortScanDiscoverySource)


async def test_run_source_unknown_type_returns_empty() -> None:
    assert await run_source("kubernetes", {}) == []


async def test_run_source_dispatches_to_registered_source(monkeypatch) -> None:
    async def fake_run(self, params):
        return ["sentinel"]

    monkeypatch.setattr(PortScanDiscoverySource, "run", fake_run)
    result = await run_source("port_scan", {"cidr": "10.0.0.0/24", "ports": [80]})
    assert result == ["sentinel"]


async def test_capability_report_reflects_each_source(monkeypatch) -> None:
    async def always_true(self):
        return True

    async def always_false(self):
        return False

    monkeypatch.setattr(DockerDiscoverySource, "capability_available", always_false)
    monkeypatch.setattr(PortScanDiscoverySource, "capability_available", always_true)

    report = await capability_report()
    assert report == {"docker": False, "port_scan": True}


async def test_capability_report_survives_a_broken_source(monkeypatch) -> None:
    async def boom(self):
        raise RuntimeError("socket probe exploded")

    monkeypatch.setattr(DockerDiscoverySource, "capability_available", boom)
    report = await capability_report()
    assert report["docker"] is False
    assert "port_scan" in report
