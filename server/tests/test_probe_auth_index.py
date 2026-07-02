"""Probe auth prefix index (C2): kill the O(n) bcrypt fleet scan.

New-scheme keys ``wiu_<prefix>.<secret>`` resolve the single candidate probe by
its indexed ``api_key_prefix`` and run exactly ONE bcrypt verification. Legacy
keys (``wiu_<secret>``, no prefix) fall back to the bcrypt scan restricted to
un-migrated probes; a key rotation moves a legacy probe onto the fast path.
"""

from __future__ import annotations

import bcrypt
import pytest
import pytest_asyncio
from fakeredis.aioredis import FakeRedis
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import whatisup.api.deps as deps
from whatisup.core.security import extract_probe_key_prefix, generate_probe_api_key
from whatisup.models.probe import NetworkType, Probe


def _fast_hash(raw: str) -> str:
    """bcrypt rounds=4 — fast enough for tests, same verify path as production."""
    return bcrypt.hashpw(raw.encode(), bcrypt.gensalt(rounds=4)).decode()


@pytest_asyncio.fixture
def count_bcrypt(monkeypatch):
    """Spy on ``deps.verify_api_key`` and count how many bcrypt checks run."""
    calls = {"n": 0}
    real = deps.verify_api_key

    def _wrapped(api_key: str, hashed: str) -> bool:
        calls["n"] += 1
        return real(api_key, hashed)

    monkeypatch.setattr(deps, "verify_api_key", _wrapped)
    return calls


async def _make_newgen_probe(
    db: AsyncSession, name: str, net: NetworkType = NetworkType.external
) -> tuple[Probe, str]:
    """Create a probe provisioned with the new ``wiu_<prefix>.<secret>`` format."""
    key, prefix = generate_probe_api_key()
    probe = Probe(
        name=name,
        location_name="DC",
        api_key_hash=_fast_hash(key),
        api_key_prefix=prefix,
        network_type=net,
    )
    db.add(probe)
    await db.flush()
    return probe, key


async def _make_legacy_probe(db: AsyncSession, name: str, key: str) -> Probe:
    """Create a legacy probe: known ``wiu_<secret>`` key, NULL prefix."""
    probe = Probe(
        name=name,
        location_name="DC",
        api_key_hash=_fast_hash(key),
        api_key_prefix=None,
        network_type=NetworkType.external,
    )
    db.add(probe)
    await db.flush()
    return probe


# ── Key format helpers ────────────────────────────────────────────────────────


def test_generate_probe_api_key_format() -> None:
    key, prefix = generate_probe_api_key()
    assert key.startswith("wiu_")
    assert key == f"wiu_{prefix}.{key.split('.', 1)[1]}"
    assert extract_probe_key_prefix(key) == prefix
    # The prefix on its own is not a usable key (no secret, no dot).
    assert extract_probe_key_prefix(f"wiu_{prefix}") is None


def test_extract_prefix_legacy_key_returns_none() -> None:
    # Legacy keys never contain a dot → no derivable prefix → scan fallback.
    assert extract_probe_key_prefix("wiu_legacyplainsecrettoken") is None
    assert extract_probe_key_prefix("not_a_probe_key") is None


# ── New-gen probe → exactly ONE bcrypt ────────────────────────────────────────


@pytest.mark.asyncio
async def test_newgen_probe_uses_single_bcrypt(
    client: AsyncClient, db_session: AsyncSession, count_bcrypt: dict
) -> None:
    """With several new-gen probes, auth runs exactly one bcrypt (indexed lookup)."""
    _p1, _k1 = await _make_newgen_probe(db_session, "ng-1")
    _p2, _k2 = await _make_newgen_probe(db_session, "ng-2")
    target, key = await _make_newgen_probe(db_session, "ng-3")

    resp = await client.post("/api/v1/probes/heartbeat", json={}, headers={"X-Probe-Api-Key": key})
    assert resp.status_code == 200, resp.text
    assert count_bcrypt["n"] == 1, "prefix lookup must isolate a single candidate"


@pytest.mark.asyncio
async def test_unknown_prefix_no_bcrypt(
    client: AsyncClient, db_session: AsyncSession, count_bcrypt: dict
) -> None:
    """A new-scheme key whose prefix matches nothing → 401 with zero bcrypt."""
    await _make_newgen_probe(db_session, "ng-only")
    bogus, _ = generate_probe_api_key()  # valid format, unknown prefix

    resp = await client.post(
        "/api/v1/probes/heartbeat", json={}, headers={"X-Probe-Api-Key": bogus}
    )
    assert resp.status_code == 401, resp.text
    assert resp.json()["detail"] == "Invalid probe API key"
    assert count_bcrypt["n"] == 0


# ── Legacy probe → scan fallback still works ──────────────────────────────────


@pytest.mark.asyncio
async def test_legacy_probe_scan_fallback(
    client: AsyncClient, db_session: AsyncSession, count_bcrypt: dict
) -> None:
    """A pre-migration probe (NULL prefix) still authenticates via the scan."""
    legacy_key = "wiu_legacyplainsecretwithoutdot"
    await _make_legacy_probe(db_session, "legacy-1", legacy_key)

    resp = await client.post(
        "/api/v1/probes/heartbeat", json={}, headers={"X-Probe-Api-Key": legacy_key}
    )
    assert resp.status_code == 200, resp.text
    assert count_bcrypt["n"] >= 1  # scan path


@pytest.mark.asyncio
async def test_newgen_probes_excluded_from_legacy_scan(
    client: AsyncClient, db_session: AsyncSession, count_bcrypt: dict
) -> None:
    """A legacy key must not bcrypt against migrated (prefixed) probes.

    Only ``api_key_prefix IS NULL`` rows are in the scan set, so a single legacy
    probe alongside several new-gen ones costs exactly one bcrypt.
    """
    await _make_newgen_probe(db_session, "ng-a")
    await _make_newgen_probe(db_session, "ng-b")
    legacy_key = "wiu_solelegacysecretnodot"
    await _make_legacy_probe(db_session, "legacy-solo", legacy_key)

    resp = await client.post(
        "/api/v1/probes/heartbeat", json={}, headers={"X-Probe-Api-Key": legacy_key}
    )
    assert resp.status_code == 200, resp.text
    assert count_bcrypt["n"] == 1


@pytest.mark.asyncio
async def test_unknown_legacy_key_rejected(client: AsyncClient, db_session: AsyncSession) -> None:
    """Unknown legacy-shaped key → 401 (no candidate matches the scan)."""
    await _make_legacy_probe(db_session, "legacy-x", "wiu_realsecretnodot")
    resp = await client.post(
        "/api/v1/probes/heartbeat",
        json={},
        headers={"X-Probe-Api-Key": "wiu_wrongsecretnodot"},
    )
    assert resp.status_code == 401, resp.text


# ── Rotation moves a legacy probe onto the fast path ──────────────────────────


@pytest.mark.asyncio
async def test_rotation_migrates_legacy_probe_to_fast_path(
    client: AsyncClient,
    db_session: AsyncSession,
    admin_token: str,
    fake_redis: FakeRedis,
    count_bcrypt: dict,
) -> None:
    """After rotation the probe has a prefix and authenticates with one bcrypt."""
    legacy_key = "wiu_prerotationsecretnodot"
    probe = await _make_legacy_probe(db_session, "to-rotate", legacy_key)
    assert probe.api_key_prefix is None

    rot = await client.post(
        f"/api/v1/probes/{probe.id}/rotate-key",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert rot.status_code == 200, rot.text
    new_key = rot.json()["api_key"]
    assert new_key.startswith("wiu_")
    assert extract_probe_key_prefix(new_key) is not None

    # Prefix now persisted → probe left the legacy scan set.
    refreshed = (await db_session.execute(select(Probe).where(Probe.id == probe.id))).scalar_one()
    assert refreshed.api_key_prefix == extract_probe_key_prefix(new_key)

    # Old key rejected (hash overwritten + cache evicted).
    old = await client.post(
        "/api/v1/probes/heartbeat", json={}, headers={"X-Probe-Api-Key": legacy_key}
    )
    assert old.status_code == 401, old.text

    # New key authenticates via the indexed fast path — single bcrypt.
    count_bcrypt["n"] = 0
    new = await client.post(
        "/api/v1/probes/heartbeat", json={}, headers={"X-Probe-Api-Key": new_key}
    )
    assert new.status_code == 200, new.text
    assert count_bcrypt["n"] == 1
