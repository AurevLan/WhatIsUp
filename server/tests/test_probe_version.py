"""Probe fleet versioning — heartbeat stores the agent version, API exposes it."""

from __future__ import annotations

from importlib.metadata import version as pkg_version

import bcrypt
import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.core.config import Settings
from whatisup.models.probe import Probe

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
