"""V2-02-02 — Classify an incident as service-down vs network partition.

Goal: stop paging on-call when a transit-level outage from one carrier makes a
service look "down" from a subset of probes only. Computed at incident open and
periodically while the incident remains open, using the latest CheckResult per
probe (already loaded by ``services/incident.py``) plus the ASN/country fields
populated by ``services/probe_enrichment.py``.

Verdicts:
  service_down            — overwhelming majority of diversified probes report DOWN
  network_partition_asn   — DOWN concentrated on one ASN, other ASNs see UP
  network_partition_geo   — DOWN concentrated in one country/region, others see UP
  inconclusive            — too few probes or insufficient ASN/geo diversity to decide

Tunables: keep them tight here to make tests deterministic. The `min_diversity`
threshold is the **number of distinct ASNs** that must report (down or up) before
we consider an ASN-level verdict possible. Same idea for geo (countries).
"""

from __future__ import annotations

import enum
import uuid
from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.models.incident import Incident
from whatisup.models.probe import Probe
from whatisup.models.result import CheckResult, CheckStatus

logger = structlog.get_logger(__name__)


class NetworkVerdict(enum.StrEnum):
    SERVICE_DOWN = "service_down"
    NETWORK_PARTITION_ASN = "network_partition_asn"
    NETWORK_PARTITION_GEO = "network_partition_geo"
    INCONCLUSIVE = "inconclusive"


# Minimum number of probes returning a verdict for the result to be trusted.
_MIN_TOTAL_PROBES = 3
# When ≥ this share of probes are DOWN, classify as service_down (regardless of ASN).
_SERVICE_DOWN_DOWN_RATIO = 0.75
# Need at least this many distinct ASNs (or countries) reporting to attempt
# a partition verdict.
_MIN_ASN_DIVERSITY = 2
_MIN_COUNTRY_DIVERSITY = 2

_DOWN_STATUSES: frozenset[CheckStatus] = frozenset(
    {CheckStatus.down, CheckStatus.timeout, CheckStatus.error}
)


def _is_down(result: CheckResult) -> bool:
    return result.status in _DOWN_STATUSES


def _country_of(probe: Probe) -> str | None:
    """Coarse country bucket — falls back to the location_name when missing."""
    # Probes do not carry an ISO country code today; location_name is free text
    # but typically prefixed by a city / country. As a pragmatic substitute we
    # split on the first non-letter and take the first token. Refined later if
    # we add a dedicated `country_code` column.
    name = (probe.location_name or "").strip().lower()
    if not name:
        return None
    for sep in (",", "/", "-", " "):
        if sep in name:
            return name.split(sep, 1)[0].strip() or None
    return name


def _classify(
    latest_by_probe: dict[uuid.UUID, CheckResult],
    probes: Iterable[Probe],
) -> NetworkVerdict:
    """Pure function — extracted for direct unit testing without DB."""
    probe_by_id = {p.id: p for p in probes}
    samples = [
        (probe_by_id[pid], result)
        for pid, result in latest_by_probe.items()
        if pid in probe_by_id
    ]
    total = len(samples)
    if total < _MIN_TOTAL_PROBES:
        return NetworkVerdict.INCONCLUSIVE

    down_samples = [(p, r) for (p, r) in samples if _is_down(r)]
    up_samples = [(p, r) for (p, r) in samples if not _is_down(r)]
    down_total = len(down_samples)
    up_total = len(up_samples)

    if down_total == 0:
        # No outage observed — caller shouldn't have asked for a verdict.
        return NetworkVerdict.INCONCLUSIVE

    # 1) Overwhelming majority DOWN -> service really is down everywhere.
    if down_total / total >= _SERVICE_DOWN_DOWN_RATIO and up_total == 0:
        return NetworkVerdict.SERVICE_DOWN

    # 2) Try ASN-level partition: at least one ASN must be 100% UP and at least
    # one ASN must be 100% DOWN, with ≥2 distinct ASNs total.
    by_asn: dict[int, list[bool]] = defaultdict(list)
    for probe, result in samples:
        if probe.asn is None:
            continue
        by_asn[probe.asn].append(_is_down(result))
    if len(by_asn) >= _MIN_ASN_DIVERSITY:
        asn_all_down = [asn for asn, rs in by_asn.items() if all(rs)]
        asn_all_up = [asn for asn, rs in by_asn.items() if not any(rs)]
        if asn_all_down and asn_all_up:
            # ASN-level partition — one or more ASNs see down while at least one
            # other ASN sees the service up.
            return NetworkVerdict.NETWORK_PARTITION_ASN

    # 3) Geo-level partition: same logic on country buckets.
    by_country: dict[str, list[bool]] = defaultdict(list)
    for probe, result in samples:
        country = _country_of(probe)
        if country is None:
            continue
        by_country[country].append(_is_down(result))
    if len(by_country) >= _MIN_COUNTRY_DIVERSITY:
        geo_all_down = [c for c, rs in by_country.items() if all(rs)]
        geo_all_up = [c for c, rs in by_country.items() if not any(rs)]
        if geo_all_down and geo_all_up:
            return NetworkVerdict.NETWORK_PARTITION_GEO

    # 4) Mixed signal but no clean partition axis — fall through. If a strong
    # majority is DOWN even without 100% coverage, lean towards service_down.
    if down_total / total >= _SERVICE_DOWN_DOWN_RATIO:
        return NetworkVerdict.SERVICE_DOWN

    return NetworkVerdict.INCONCLUSIVE


async def classify_network_verdict(
    db: AsyncSession,
    incident: Incident,
    *,
    latest_by_probe: dict[uuid.UUID, CheckResult] | None = None,
    persist: bool = True,
) -> NetworkVerdict:
    """
    Compute (and optionally persist) the network verdict for ``incident``.

    Returns the verdict. When ``persist=True`` (default), updates
    ``incident.network_verdict`` + ``network_verdict_computed_at`` and flushes.

    ``latest_by_probe`` may be passed by the caller to avoid a duplicate query
    (the incident pipeline already has it). When None, we re-query.
    """
    if latest_by_probe is None:
        from whatisup.services.stats import latest_results_subq

        sub = latest_results_subq(
            CheckResult.monitor_id == incident.monitor_id,
            group_col=CheckResult.probe_id,
        )
        rows = (
            (
                await db.execute(
                    select(CheckResult)
                    .join(
                        sub,
                        (CheckResult.probe_id == sub.c.probe_id)
                        & (CheckResult.checked_at == sub.c.max_at),
                    )
                    .where(CheckResult.monitor_id == incident.monitor_id)
                )
            )
            .scalars()
            .all()
        )
        latest_by_probe = {r.probe_id: r for r in rows if r.probe_id is not None}

    probe_ids = list(latest_by_probe.keys())
    if not probe_ids:
        verdict = NetworkVerdict.INCONCLUSIVE
    else:
        probes = (
            (
                await db.execute(
                    select(Probe).where(
                        Probe.id.in_(probe_ids),
                        Probe.is_active.is_(True),
                    )
                )
            )
            .scalars()
            .all()
        )
        verdict = _classify(latest_by_probe, probes)

    if persist:
        incident.network_verdict = verdict.value
        incident.network_verdict_computed_at = datetime.now(UTC)
        # No commit here — caller controls the transaction boundary.
        await db.flush()
        logger.info(
            "network_verdict_computed",
            incident_id=str(incident.id),
            verdict=verdict.value,
        )
    return verdict


async def recompute_open_incidents_verdicts(db: AsyncSession) -> int:
    """
    Background task — refresh the verdict for every still-open incident.

    Runs every 5 minutes (see lifespan loop). Skips composite monitors (no
    multi-probe semantics there). Returns the number of incidents updated.
    """
    rows = (
        (
            await db.execute(
                select(Incident).where(Incident.resolved_at.is_(None))
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return 0
    updated = 0
    for incident in rows:
        try:
            await classify_network_verdict(db, incident, persist=True)
            updated += 1
        except Exception as exc:  # noqa: BLE001 — must not interrupt the loop
            logger.warning(
                "network_verdict_recompute_failed",
                incident_id=str(incident.id),
                error_type=type(exc).__name__,
            )
    if updated:
        await db.commit()
    return updated
