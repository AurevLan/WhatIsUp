"""Probe fleet versioning — heartbeat stores the agent version, API exposes it."""

from __future__ import annotations

from importlib.metadata import version as pkg_version

import bcrypt
import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.core.config import Settings, get_settings
from whatisup.models.probe import Probe
from whatisup.services.probe_version import (
    AGENT_STATUS_CURRENT,
    AGENT_STATUS_OUTDATED,
    AGENT_STATUS_UNREPORTED,
    agent_status_for,
    compare_versions,
)

_PROBE_KEY = "wiu_version_probe_key_only_used_in_tests"
_PROBE_HEADERS = {"X-Probe-Api-Key": _PROBE_KEY}


@pytest_asyncio.fixture
async def probe_with_key(db_session: AsyncSession) -> Probe:
    key_hash = bcrypt.hashpw(_PROBE_KEY.encode(), bcrypt.gensalt(rounds=4)).decode()
    probe = Probe(name="version-probe", location_name="Test DC", api_key_hash=key_hash)
    db_session.add(probe)
    await db_session.flush()
    return probe


@pytest.mark.asyncio
async def test_heartbeat_stores_probe_version(
    client: AsyncClient, probe_with_key: Probe, admin_token: str
) -> None:
    resp = await client.post(
        "/api/v1/probes/heartbeat",
        json={"version": "1.12.0"},
        headers=_PROBE_HEADERS,
    )
    assert resp.status_code == 200
    assert probe_with_key.version == "1.12.0"

    # Exposed in the probes list for the UI badge
    listed = await client.get("/api/v1/probes/", headers={"Authorization": f"Bearer {admin_token}"})
    assert listed.status_code == 200
    me = next(p for p in listed.json() if p["name"] == "version-probe")
    assert me["version"] == "1.12.0"


@pytest.mark.asyncio
async def test_heartbeat_without_version_keeps_null(
    client: AsyncClient, probe_with_key: Probe
) -> None:
    """Pre-1.12 probes don't send a version — column stays null (UI shows 'unknown')."""
    resp = await client.post("/api/v1/probes/heartbeat", json={}, headers=_PROBE_HEADERS)
    assert resp.status_code == 200
    assert probe_with_key.version is None


def test_app_version_comes_from_package_metadata() -> None:
    """app_version must track the release (release-please bumps pyproject)."""
    assert Settings(secret_key="x" * 32, environment="test").app_version == pkg_version(
        "whatisup-server"
    )


# ── agent_status classification (services/probe_version.py) ────────────────


def test_compare_versions_is_numeric_not_lexicographic() -> None:
    """A string compare would rank "1.9.0" above "1.10.0" — must not happen."""
    assert compare_versions("1.9.0", "1.10.0") == -1
    assert compare_versions("1.10.0", "1.9.0") == 1
    assert compare_versions("1.10.0", "1.10.0") == 0


def test_compare_versions_tolerates_pre_release_suffixes() -> None:
    assert compare_versions("1.24.0-rc1", "1.24.0") == 0
    assert compare_versions("1.24.0+build3", "1.24.0") == 0


def test_agent_status_unreported_when_probe_has_no_version() -> None:
    """The case that motivated this lot: a probe too old to announce a version
    is the one that most needs the warning, not one exempt from it."""
    assert agent_status_for(None, "1.27.0") == AGENT_STATUS_UNREPORTED
    assert agent_status_for("", "1.27.0") == AGENT_STATUS_UNREPORTED


def test_agent_status_current_when_matching_server() -> None:
    assert agent_status_for("1.27.0", "1.27.0") == AGENT_STATUS_CURRENT


def test_agent_status_current_when_newer_than_server() -> None:
    """A probe running a newer agent than the server (mid-rollout) is not a
    problem — must never be reported as outdated."""
    assert agent_status_for("1.28.0", "1.27.0") == AGENT_STATUS_CURRENT


def test_agent_status_outdated_when_older_than_server() -> None:
    assert agent_status_for("1.24.0", "1.27.0") == AGENT_STATUS_OUTDATED


# ── agent_status on ProbeOut / GET /probes/ ─────────────────────────────────


@pytest.mark.asyncio
async def test_probe_list_reports_unreported_agent_status(
    client: AsyncClient, probe_with_key: Probe, admin_token: str
) -> None:
    resp = await client.post("/api/v1/probes/heartbeat", json={}, headers=_PROBE_HEADERS)
    assert resp.status_code == 200

    listed = await client.get("/api/v1/probes/", headers={"Authorization": f"Bearer {admin_token}"})
    me = next(p for p in listed.json() if p["name"] == "version-probe")
    assert me["version"] is None
    assert me["agent_status"] == "unreported"


@pytest.mark.asyncio
async def test_probe_list_reports_current_agent_status(
    client: AsyncClient, probe_with_key: Probe, admin_token: str
) -> None:
    server_version = get_settings().app_version
    resp = await client.post(
        "/api/v1/probes/heartbeat", json={"version": server_version}, headers=_PROBE_HEADERS
    )
    assert resp.status_code == 200

    listed = await client.get("/api/v1/probes/", headers={"Authorization": f"Bearer {admin_token}"})
    me = next(p for p in listed.json() if p["name"] == "version-probe")
    assert me["agent_status"] == "current"


@pytest.mark.asyncio
async def test_probe_list_never_reports_newer_agent_as_outdated(
    client: AsyncClient, probe_with_key: Probe, admin_token: str
) -> None:
    resp = await client.post(
        "/api/v1/probes/heartbeat", json={"version": "999.0.0"}, headers=_PROBE_HEADERS
    )
    assert resp.status_code == 200

    listed = await client.get("/api/v1/probes/", headers={"Authorization": f"Bearer {admin_token}"})
    me = next(p for p in listed.json() if p["name"] == "version-probe")
    assert me["agent_status"] == "current"


@pytest.mark.asyncio
async def test_probe_list_reports_outdated_agent_status(
    client: AsyncClient, probe_with_key: Probe, admin_token: str
) -> None:
    resp = await client.post(
        "/api/v1/probes/heartbeat", json={"version": "0.0.1"}, headers=_PROBE_HEADERS
    )
    assert resp.status_code == 200

    listed = await client.get("/api/v1/probes/", headers={"Authorization": f"Bearer {admin_token}"})
    me = next(p for p in listed.json() if p["name"] == "version-probe")
    assert me["agent_status"] == "outdated"


@pytest.mark.asyncio
async def test_probe_stats_also_exposes_agent_status(
    client: AsyncClient, probe_with_key: Probe, admin_token: str
) -> None:
    """``/probes/stats`` inherits ``ProbeOut`` (PR #412) — a computed field
    added there must reach this endpoint too, with no re-declaration needed."""
    resp = await client.post(
        "/api/v1/probes/heartbeat", json={"version": "0.0.1"}, headers=_PROBE_HEADERS
    )
    assert resp.status_code == 200

    stats = await client.get(
        "/api/v1/probes/stats", headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert stats.status_code == 200
    me = next(p for p in stats.json() if p["name"] == "version-probe")
    assert me["agent_status"] == "outdated"
