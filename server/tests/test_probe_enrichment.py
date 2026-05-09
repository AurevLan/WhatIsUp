"""V2-02-01 — Tests for ASN enrichment of probes (services/probe_enrichment.py)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.models.probe import Probe
from whatisup.services.probe_enrichment import (
    AsnInfo,
    _circuit_open,
    _circuit_reset,
    _cymru_origin_query,
    _parse_cymru_asn_txt,
    _parse_cymru_origin_txt,
    enrich_probe,
    is_public_ip,
    lookup_asn,
    maybe_enrich_on_heartbeat,
)


@pytest.fixture(autouse=True)
def _reset_breaker() -> None:
    """Each test starts with a closed circuit breaker."""
    _circuit_reset()
    yield
    _circuit_reset()

# ── Pure parsing / helpers (no I/O) ───────────────────────────────────────────


def test_is_public_ip_filters_private_and_loopback() -> None:
    assert is_public_ip("8.8.8.8")
    assert is_public_ip("1.1.1.1")
    assert not is_public_ip("127.0.0.1")
    assert not is_public_ip("10.0.0.5")
    assert not is_public_ip("192.168.1.1")
    assert not is_public_ip("172.20.0.3")
    assert not is_public_ip("169.254.0.1")  # link-local
    assert not is_public_ip("::1")
    assert not is_public_ip("not-an-ip")


def test_cymru_origin_query_reverses_octets_for_ipv4() -> None:
    assert _cymru_origin_query("8.8.8.8") == "8.8.8.8.origin.asn.cymru.com"
    assert _cymru_origin_query("1.2.3.4") == "4.3.2.1.origin.asn.cymru.com"


def test_parse_cymru_origin_txt_extracts_asn_and_country() -> None:
    txt = '15169 | 8.8.8.0/24 | US | arin | 1992-12-01'
    asn, country = _parse_cymru_origin_txt(txt)
    assert asn == 15169
    assert country == "US"


def test_parse_cymru_origin_txt_returns_none_on_garbage() -> None:
    asn, country = _parse_cymru_origin_txt("garbage data")
    assert asn is None
    assert country is None


def test_parse_cymru_asn_txt_extracts_organisation() -> None:
    txt = '15169 | US | arin | 2000-03-30 | GOOGLE, US'
    name = _parse_cymru_asn_txt(txt)
    assert name == "GOOGLE, US"


# ── enrich_probe — DB integration with mocked DNS ─────────────────────────────


@pytest.mark.asyncio
async def test_enrich_probe_persists_asn_info(service_db: AsyncSession) -> None:
    probe = Probe(name="p1", location_name="Paris", api_key_hash="x")
    service_db.add(probe)
    await service_db.flush()

    fake_info = AsnInfo(asn=15169, asn_name="GOOGLE, US", country="US")
    with patch(
        "whatisup.services.probe_enrichment.lookup_asn",
        return_value=fake_info,
    ):
        updated = await enrich_probe(service_db, probe, "8.8.8.8")

    assert updated is True
    assert probe.public_ip == "8.8.8.8"
    assert probe.asn == 15169
    assert probe.asn_name == "GOOGLE, US"
    assert probe.asn_updated_at is not None


@pytest.mark.asyncio
async def test_enrich_probe_skips_private_ip(service_db: AsyncSession) -> None:
    probe = Probe(name="p2", location_name="LAN", api_key_hash="x")
    service_db.add(probe)
    await service_db.flush()

    updated = await enrich_probe(service_db, probe, "10.0.0.1")

    assert updated is False
    assert probe.asn is None
    assert probe.public_ip is None


@pytest.mark.asyncio
async def test_enrich_probe_marks_attempt_when_lookup_fails(
    service_db: AsyncSession,
) -> None:
    """When Cymru returns nothing, persist the IP + timestamp to avoid retrying
    on every heartbeat."""
    probe = Probe(name="p3", location_name="Paris", api_key_hash="x")
    service_db.add(probe)
    await service_db.flush()

    with patch("whatisup.services.probe_enrichment.lookup_asn", return_value=None):
        updated = await enrich_probe(service_db, probe, "1.0.0.1")

    assert updated is True
    assert probe.public_ip == "1.0.0.1"
    assert probe.asn is None
    assert probe.asn_updated_at is not None


@pytest.mark.asyncio
async def test_maybe_enrich_skips_when_data_is_fresh(
    service_db: AsyncSession,
) -> None:
    """Heartbeat must not trigger a new lookup if asn data is recent."""
    probe = Probe(
        name="p4",
        location_name="Paris",
        api_key_hash="x",
        public_ip="8.8.8.8",
        asn=15169,
        asn_name="GOOGLE, US",
        asn_updated_at=datetime.now(UTC) - timedelta(hours=1),
    )
    service_db.add(probe)
    await service_db.flush()

    with patch(
        "whatisup.services.probe_enrichment.enrich_probe"
    ) as mock_enrich:
        await maybe_enrich_on_heartbeat(service_db, probe, "8.8.8.8")

    mock_enrich.assert_not_called()


# ── Cymru query format ────────────────────────────────────────────────────────


def test_cymru_origin_query_uses_origin6_for_ipv6() -> None:
    """IPv6 addresses must hit the origin6 zone with reversed nibbles, not origin."""
    result = _cymru_origin_query("2001:4860:4860::8888")
    assert result.endswith(".origin6.asn.cymru.com")
    # 2001:4860:4860:0000:0000:0000:0000:8888 -> exploded
    # nibbles reversed: starts with 8 (last char of last group)
    assert result.startswith("8.8.8.8.")


def test_parse_cymru_asn_txt_handles_short_txt() -> None:
    """Cymru name TXT with fewer than 5 fields means no organisation name."""
    assert _parse_cymru_asn_txt("15169 | US | arin") is None


# ── lookup_asn — backend gating + circuit breaker ─────────────────────────────


@pytest.mark.asyncio
async def test_lookup_asn_returns_none_when_backend_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from whatisup.core.config import get_settings
    settings = get_settings()
    monkeypatch.setattr(settings, "asn_lookup_provider", "disabled")
    assert await lookup_asn("8.8.8.8") is None


@pytest.mark.asyncio
async def test_lookup_asn_returns_none_for_private_ip() -> None:
    assert await lookup_asn("10.0.0.1") is None


@pytest.mark.asyncio
async def test_lookup_asn_opens_breaker_after_threshold_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """5 consecutive failures within the rolling window flip the breaker open."""
    from whatisup.core.config import get_settings
    settings = get_settings()
    monkeypatch.setattr(settings, "asn_lookup_provider", "cymru")

    fail_call = AsyncMock(return_value=None)
    monkeypatch.setattr(
        "whatisup.services.probe_enrichment._lookup_via_cymru",
        fail_call,
    )

    # 5 failures → breaker opens after the 5th
    for _ in range(5):
        result = await lookup_asn("8.8.8.8")
        assert result is None

    assert _circuit_open()
    # 6th call must short-circuit and not invoke the resolver again
    before = fail_call.call_count
    assert await lookup_asn("8.8.8.8") is None
    assert fail_call.call_count == before


@pytest.mark.asyncio
async def test_lookup_asn_breaker_closes_on_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A single successful lookup wipes the failure counter and reopens traffic."""
    from whatisup.core.config import get_settings
    settings = get_settings()
    monkeypatch.setattr(settings, "asn_lookup_provider", "cymru")

    # 3 failures (under threshold), then a success
    fake = AsyncMock(side_effect=[None, None, None, AsnInfo(asn=15169, asn_name="G")])
    monkeypatch.setattr(
        "whatisup.services.probe_enrichment._lookup_via_cymru",
        fake,
    )

    for _ in range(3):
        await lookup_asn("8.8.8.8")
    assert not _circuit_open()

    result = await lookup_asn("8.8.8.8")
    assert result is not None
    assert result.asn == 15169
    # success cleared internal state — breaker still closed and counter empty
    assert not _circuit_open()
