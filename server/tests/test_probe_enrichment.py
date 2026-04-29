"""V2-02-01 — Tests for ASN enrichment of probes (services/probe_enrichment.py)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.models.probe import Probe
from whatisup.services.probe_enrichment import (
    AsnInfo,
    _cymru_origin_query,
    _parse_cymru_asn_txt,
    _parse_cymru_origin_txt,
    enrich_probe,
    is_public_ip,
    maybe_enrich_on_heartbeat,
)

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
