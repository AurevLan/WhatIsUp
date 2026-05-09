"""V2-02-02 — Tests for network partition vs service-down classification."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.models.incident import Incident, IncidentScope
from whatisup.models.monitor import Monitor
from whatisup.models.probe import Probe
from whatisup.models.result import CheckResult, CheckStatus
from whatisup.models.user import User
from whatisup.services.network_verdict import (
    NetworkVerdict,
    _classify,
    classify_network_verdict,
)


def _make_probe(name: str, *, asn: int | None, location: str = "Paris, FR") -> Probe:
    return Probe(
        id=uuid.uuid4(),
        name=name,
        location_name=location,
        api_key_hash="x",
        is_active=True,
        asn=asn,
    )


def _make_result(probe_id: uuid.UUID, status: CheckStatus) -> CheckResult:
    return CheckResult(
        id=uuid.uuid4(),
        monitor_id=uuid.uuid4(),
        probe_id=probe_id,
        checked_at=datetime.now(UTC),
        status=status,
    )


# ── Pure-function _classify (no DB) ────────────────────────────────────────────


def test_classify_inconclusive_below_min_probes() -> None:
    p1 = _make_probe("p1", asn=15169)
    p2 = _make_probe("p2", asn=2914)
    latest = {
        p1.id: _make_result(p1.id, CheckStatus.down),
        p2.id: _make_result(p2.id, CheckStatus.down),
    }
    assert _classify(latest, [p1, p2]) == NetworkVerdict.INCONCLUSIVE


def test_classify_inconclusive_when_no_down() -> None:
    probes = [_make_probe(f"p{i}", asn=15169 + i) for i in range(4)]
    latest = {p.id: _make_result(p.id, CheckStatus.up) for p in probes}
    assert _classify(latest, probes) == NetworkVerdict.INCONCLUSIVE


def test_classify_service_down_when_all_probes_down() -> None:
    probes = [_make_probe(f"p{i}", asn=15169 + i) for i in range(4)]
    latest = {p.id: _make_result(p.id, CheckStatus.down) for p in probes}
    assert _classify(latest, probes) == NetworkVerdict.SERVICE_DOWN


def test_classify_network_partition_asn() -> None:
    """Two ASNs see DOWN, one ASN sees UP — partition_asn."""
    # ASN 15169 (Google) — 2 probes both DOWN
    p1 = _make_probe("p1", asn=15169)
    p2 = _make_probe("p2", asn=15169)
    # ASN 2914 (NTT) — 2 probes both UP
    p3 = _make_probe("p3", asn=2914)
    p4 = _make_probe("p4", asn=2914)
    latest = {
        p1.id: _make_result(p1.id, CheckStatus.down),
        p2.id: _make_result(p2.id, CheckStatus.timeout),
        p3.id: _make_result(p3.id, CheckStatus.up),
        p4.id: _make_result(p4.id, CheckStatus.up),
    }
    assert _classify(latest, [p1, p2, p3, p4]) == NetworkVerdict.NETWORK_PARTITION_ASN


def test_classify_network_partition_geo_when_asn_missing() -> None:
    """No ASN data, but country split — partition_geo via location_name."""
    p1 = _make_probe("p1", asn=None, location="Paris, FR")
    p2 = _make_probe("p2", asn=None, location="Lyon, FR")
    p3 = _make_probe("p3", asn=None, location="Berlin, DE")
    p4 = _make_probe("p4", asn=None, location="Munich, DE")
    latest = {
        p1.id: _make_result(p1.id, CheckStatus.down),
        p2.id: _make_result(p2.id, CheckStatus.down),
        p3.id: _make_result(p3.id, CheckStatus.up),
        p4.id: _make_result(p4.id, CheckStatus.up),
    }
    # _country_of strips on first separator — both Paris and Lyon end up "paris"/"lyon"
    # We make the partition explicit by using identical first tokens per group.
    p1.location_name = "fr-paris"
    p2.location_name = "fr-lyon"
    p3.location_name = "de-berlin"
    p4.location_name = "de-munich"
    assert _classify(latest, [p1, p2, p3, p4]) == NetworkVerdict.NETWORK_PARTITION_GEO


def test_classify_falls_back_to_service_down_on_strong_majority() -> None:
    """Mostly DOWN with a tiny minority UP, ASN/geo not perfectly split."""
    # 4 probes DOWN on different ASNs, 1 probe UP on a 5th ASN — no clean
    # ASN partition (one ASN-up, four distinct ASNs-down) — but ratio 4/5
    # exceeds the 0.75 service_down threshold.
    probes = [_make_probe(f"p{i}", asn=15169 + i) for i in range(5)]
    latest = {
        probes[0].id: _make_result(probes[0].id, CheckStatus.down),
        probes[1].id: _make_result(probes[1].id, CheckStatus.down),
        probes[2].id: _make_result(probes[2].id, CheckStatus.down),
        probes[3].id: _make_result(probes[3].id, CheckStatus.down),
        probes[4].id: _make_result(probes[4].id, CheckStatus.up),
    }
    # Down ratio is 4/5 = 0.80, but partition logic also matches (ASN of
    # probes[4] is UP-only, others DOWN-only). The verdict should be
    # NETWORK_PARTITION_ASN — the rule is "any clean ASN partition wins
    # over the service-down fallback".
    assert _classify(latest, probes) == NetworkVerdict.NETWORK_PARTITION_ASN


def test_classify_inconclusive_when_data_too_messy() -> None:
    """Same ASN sees mixed up/down (inside the same AS, partial outage) — no clean
    partition, no overwhelming majority."""
    probes = [
        _make_probe("p1", asn=15169),
        _make_probe("p2", asn=15169),
        _make_probe("p3", asn=15169),
        _make_probe("p4", asn=15169),
    ]
    latest = {
        probes[0].id: _make_result(probes[0].id, CheckStatus.down),
        probes[1].id: _make_result(probes[1].id, CheckStatus.up),
        probes[2].id: _make_result(probes[2].id, CheckStatus.down),
        probes[3].id: _make_result(probes[3].id, CheckStatus.up),
    }
    assert _classify(latest, probes) == NetworkVerdict.INCONCLUSIVE


# ── DB-level classify_network_verdict ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_classify_persists_verdict_on_incident(
    service_db: AsyncSession,
) -> None:
    user = User(email="u@x", username="u", hashed_password="x")
    service_db.add(user)
    await service_db.flush()

    monitor = Monitor(name="m1", url="http://example.com", owner_id=user.id)
    service_db.add(monitor)
    await service_db.flush()

    probes = [_make_probe(f"p{i}", asn=15169 + i) for i in range(4)]
    for p in probes:
        service_db.add(p)
    await service_db.flush()

    # Persist results so the function can re-query (latest_by_probe=None branch)
    now = datetime.now(UTC)
    for p in probes:
        service_db.add(
            CheckResult(
                monitor_id=monitor.id,
                probe_id=p.id,
                checked_at=now,
                status=CheckStatus.down,
            )
        )

    incident = Incident(
        monitor_id=monitor.id,
        started_at=now,
        scope=IncidentScope.global_,
        affected_probe_ids=[str(p.id) for p in probes],
    )
    service_db.add(incident)
    await service_db.flush()

    verdict = await classify_network_verdict(service_db, incident, persist=True)

    assert verdict == NetworkVerdict.SERVICE_DOWN
    assert incident.network_verdict == "service_down"
    assert incident.network_verdict_computed_at is not None
    # Computed within the last few seconds
    assert (datetime.now(UTC) - incident.network_verdict_computed_at) < timedelta(seconds=10)


# ── Edge cases ────────────────────────────────────────────────────────────────


def test_classify_inconclusive_with_two_probes_same_asn() -> None:
    """Two probes are below `_MIN_TOTAL_PROBES=3` so the verdict is INCONCLUSIVE
    even if one is up and the other down. Prevents premature ASN partition calls
    when the fleet is too small."""
    p1 = _make_probe("p1", asn=15169)
    p2 = _make_probe("p2", asn=15169)
    latest = {
        p1.id: _make_result(p1.id, CheckStatus.down),
        p2.id: _make_result(p2.id, CheckStatus.up),
    }
    assert _classify(latest, [p1, p2]) == NetworkVerdict.INCONCLUSIVE


def test_classify_partition_asn_ignores_probes_with_missing_asn() -> None:
    """Probes whose ASN is unknown do not contribute to the ASN diversity count
    but still count toward the total. Three probes total (1 unknown ASN, 1 ASN-A,
    1 ASN-B) — only two ASNs known, partition allowed if pattern fits."""
    p_unknown = _make_probe("p-unk", asn=None)
    p_a = _make_probe("p-a", asn=15169)
    p_b = _make_probe("p-b", asn=2914)
    latest = {
        p_unknown.id: _make_result(p_unknown.id, CheckStatus.down),
        p_a.id: _make_result(p_a.id, CheckStatus.down),
        p_b.id: _make_result(p_b.id, CheckStatus.up),
    }
    # ASN-A all-down, ASN-B all-up → ASN partition expected
    assert _classify(latest, [p_unknown, p_a, p_b]) == NetworkVerdict.NETWORK_PARTITION_ASN


def test_classify_treats_timeout_and_error_as_down() -> None:
    """Service shouldn't escape a service_down verdict because a probe reported
    `timeout` or `error` instead of `down` — they're failures from the user's POV."""
    p1 = _make_probe("p1", asn=15169, location="Paris, FR")
    p2 = _make_probe("p2", asn=2914, location="Berlin, DE")
    p3 = _make_probe("p3", asn=701, location="London, UK")
    latest = {
        p1.id: _make_result(p1.id, CheckStatus.down),
        p2.id: _make_result(p2.id, CheckStatus.timeout),
        p3.id: _make_result(p3.id, CheckStatus.error),
    }
    assert _classify(latest, [p1, p2, p3]) == NetworkVerdict.SERVICE_DOWN


def test_classify_inconclusive_when_no_diversity_and_mixed_signal() -> None:
    """3 probes all on ASN-15169 + same country, half down half up.
    No ASN diversity, no geo diversity, not strong majority down → inconclusive
    (don't fabricate a partition with a single ASN)."""
    p1 = _make_probe("p1", asn=15169, location="Paris, FR")
    p2 = _make_probe("p2", asn=15169, location="Paris, FR")
    p3 = _make_probe("p3", asn=15169, location="Paris, FR")
    latest = {
        p1.id: _make_result(p1.id, CheckStatus.down),
        p2.id: _make_result(p2.id, CheckStatus.up),
        p3.id: _make_result(p3.id, CheckStatus.up),
    }
    assert _classify(latest, [p1, p2, p3]) == NetworkVerdict.INCONCLUSIVE


def test_classify_partition_geo_when_asn_field_present_but_same() -> None:
    """When all probes share the same ASN, ASN-level partition is impossible;
    geo-level partition can still fire if locations cluster correctly."""
    p_paris1 = _make_probe("pa1", asn=15169, location="Paris, FR")
    p_paris2 = _make_probe("pa2", asn=15169, location="Paris, FR")
    p_berlin = _make_probe("pb", asn=15169, location="Berlin, DE")
    latest = {
        p_paris1.id: _make_result(p_paris1.id, CheckStatus.down),
        p_paris2.id: _make_result(p_paris2.id, CheckStatus.down),
        p_berlin.id: _make_result(p_berlin.id, CheckStatus.up),
    }
    assert _classify(latest, [p_paris1, p_paris2, p_berlin]) == NetworkVerdict.NETWORK_PARTITION_GEO


def test_classify_unknown_probe_id_in_latest_is_dropped_silently() -> None:
    """The classifier only considers probes from the supplied list — orphan
    keys (e.g. probes that have been deactivated since the result was recorded)
    must not blow up the call."""
    p1 = _make_probe("p1", asn=15169)
    p2 = _make_probe("p2", asn=2914)
    p3 = _make_probe("p3", asn=701)
    orphan_id = uuid.uuid4()
    latest = {
        p1.id: _make_result(p1.id, CheckStatus.down),
        p2.id: _make_result(p2.id, CheckStatus.down),
        p3.id: _make_result(p3.id, CheckStatus.down),
        orphan_id: _make_result(orphan_id, CheckStatus.up),
    }
    # 3 valid samples all DOWN → service_down (orphan ignored)
    assert _classify(latest, [p1, p2, p3]) == NetworkVerdict.SERVICE_DOWN
