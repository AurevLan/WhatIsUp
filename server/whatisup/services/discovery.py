"""Reconciliation of discovery snapshots into reviewable proposals (plan D, D-2/D-4).

D-1 ingestion (`api/v1/probes.py::push_discovery`) only stores a snapshot —
every service is either inserted as ``proposed`` or refreshed in place, and
``status`` is never touched there (a `dismissed` row must survive a re-push
unchanged). This module is what turns a stored snapshot into the state
machine the plan promises:

- ``reconcile_source_push`` — called by ``push_discovery`` right after its
  upsert loop, still inside the same transaction. Matches new proposals
  against the owner's existing monitors (a target already monitored is
  linked, never proposed), flips services missing from the snapshot to
  ``orphaned`` (if they were ``accepted``) or drops them outright (if they
  were never acted on), and flips ``orphaned`` services whose target
  reappeared back to ``accepted``. D-4 adds one more transition: a
  ``dismissed`` row still present in the snapshot whose ``dismissal_fingerprint``
  (a stable subset of its hints) no longer matches the one captured at
  dismiss time goes back to ``proposed`` — the refusal was about a
  *different* service that happened to share this target.
- ``default_monitor_fields`` / ``compute_proposal`` — the pre-filled
  proposal (`check_type` deduced from the port, suggested name/group/tags
  from hints) surfaced by `DiscoveredServiceOut` and used as the base a
  caller of `POST /discovery/services/{id}/accept` can override.

Nothing here writes a ``Monitor`` — that stays in `api/v1/discovery.py`
(accept orchestrates the CRUD creation path), matching the chantier's one
non-negotiable rule: discovery proposes, only an explicit accept creates.
The one exception, matching, isn't a violation of that rule: it never
creates anything, it only recognizes a target the owner has *already*
turned into a monitor by hand and stops proposing it a second time.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlparse

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.models.alert_matrix_template import AlertMatrixTemplate
from whatisup.models.discovery import DiscoveredService, DiscoverySource
from whatisup.models.monitor import Monitor
from whatisup.models.probe_group import ProbeGroup

#: check_type values whose `Monitor.url` does not represent a bare
#: `host[:port]` network target the way port_scan/docker discovery reports
#: one — matching against them would either be meaningless (`heartbeat`: no
#: outbound target at all) or produce false positives (`dns`/`ping`/
#: `domain_expiry` store a queried domain with no associated port at all;
#: falling through to a default port would collide with an unrelated
#: discovered port 80/443 service on the same host). `composite` aggregates
#: other monitors and has no network target of its own.
_NON_MATCHABLE_CHECK_TYPES = frozenset({"heartbeat", "dns", "ping", "domain_expiry", "composite"})

#: `Monitor` fields that carry the real port for their check_type — the
#: check-type-specific field always wins over whatever the URL parses to
#: (mirrors how the probe checkers read config, e.g.
#: `probe/whatisup_probe/checkers/tcp.py`: `config.get("tcp_port") or parsed.port`).
_PORT_FIELD_BY_CHECK_TYPE = {"tcp": "tcp_port", "udp": "udp_port", "smtp": "smtp_port"}

#: Scheme -> default port, used only when a check_type has no dedicated port
#: field and the URL itself doesn't name one (plain `http`/`https` monitors).
_SCHEME_DEFAULT_PORTS = {"http": 80, "https": 443}

#: Ports mapped to a `check_type` deduction (plan_discovery.md D-2: "443→http,
#: 80→http, 5432/6379/etc.→tcp, 25/465/587→smtp, 53→dns…, défaut tcp"). Ports
#: not listed here — 5432, 6379, 22, ... — already fall through to the
#: tcp/udp default below; listing them would just restate that default.
_HTTP_PORTS = frozenset({80, 443, 8080, 8443, 8000})
_SMTP_PORTS = frozenset({25, 465, 587})
_DNS_PORTS = frozenset({53})

#: Docker Compose labels used for suggested group/tags — the only ones with a
#: stable, well-known meaning across the ecosystem (docker-compose CLI sets
#: them on every container it starts).
_COMPOSE_PROJECT_LABEL = "com.docker.compose.project"
_COMPOSE_SERVICE_LABEL = "com.docker.compose.service"


def deduce_check_type(port: int | None, proto: str) -> str:
    """Best-effort ``check_type`` guess from what the scan actually observed."""
    if port in _HTTP_PORTS:
        return "http"
    if port in _SMTP_PORTS:
        return "smtp"
    if port in _DNS_PORTS:
        return "dns"
    return "udp" if proto == "udp" else "tcp"


def _suggest_name(service: DiscoveredService) -> str:
    hints = service.hints or {}
    name = hints.get("container_name") or hints.get("image")
    if name:
        return str(name)[:255]
    if service.port is not None:
        return f"{service.host}:{service.port}"
    return service.host[:255]


def _suggest_group(service: DiscoveredService) -> str | None:
    labels = (service.hints or {}).get("labels")
    if not isinstance(labels, dict):
        return None
    project = labels.get(_COMPOSE_PROJECT_LABEL)
    return str(project)[:255] if project else None


def _suggest_tags(service: DiscoveredService, source_type: str) -> list[str]:
    tags = [f"discovery:{source_type}"]
    labels = (service.hints or {}).get("labels")
    if isinstance(labels, dict):
        compose_service = labels.get(_COMPOSE_SERVICE_LABEL)
        if compose_service:
            tags.append(str(compose_service)[:64])
    return tags


#: The only hint keys a dismissal fingerprint is computed from (plan D, D-4:
#: "sous-ensemble stable et documenté des hints — image docker, container_name,
#: server_header — pas les valeurs volatiles"). Everything else a source can
#: observe (labels values, http_status, TLS details, DNS record values...) is
#: excluded on purpose: those churn independently of what the service *is*,
#: and feeding them in would re-propose a dismissed service on every restart
#: or every DNS TTL expiry, making dismiss useless. A source that never
#: reports any of these three (port_scan today) always hashes the same empty
#: subset — its dismissals simply never drift, which is the correct behaviour
#: until a source starts observing something stable about the service.
_FINGERPRINT_HINT_KEYS = ("image", "container_name", "server_header")


def dismissal_fingerprint(hints: dict) -> str:
    """Stable identity of a discovered service's *nature*, as it stood at
    dismiss time — sha256 of the canonical (sorted-keys) JSON form of the
    stable hint subset, truncated like `models/custom_metric.py::series_hash`.

    Must be called with the row's live ``hints`` at the moment of the
    dismiss call, never re-derived later: ingestion refreshes ``hints`` in
    place on every push (`api/v1/probes.py::push_discovery`), so re-hashing
    a re-pushed row would compare the current value against itself and never
    detect drift.
    """
    subset = {key: hints.get(key) for key in _FINGERPRINT_HINT_KEYS if hints.get(key) is not None}
    canonical = json.dumps(subset, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()[:32]


@dataclass(frozen=True)
class ServiceProposal:
    check_type: str
    name: str
    group: str | None
    tags: list[str]


def compute_proposal(service: DiscoveredService, source_type: str) -> ServiceProposal:
    """The prefill exposed on `DiscoveredServiceOut` and used as accept()'s base."""
    return ServiceProposal(
        check_type=deduce_check_type(service.port, service.proto),
        name=_suggest_name(service),
        group=_suggest_group(service),
        tags=_suggest_tags(service, source_type),
    )


def group_capable_probe_count(group: ProbeGroup, source_type: str) -> int:
    """How many current members of *group* declare *source_type*'s capability.

    Shared by the create/update fail-visible gate (plan E, E-2: a group with
    zero capable probes is refused at write time) and the
    ``group_capable_probe_count`` field surfaced on every read afterwards (a
    probe leaving the group later must make the source *say* it can no longer
    run, never fail silently) — one computation, two call sites, so they
    cannot drift. Relies on ``ProbeGroup.probes`` being loaded — it is
    ``lazy="selectin"`` on the model, so any plain ``select(ProbeGroup)``
    already has it.
    """
    return sum(1 for p in group.probes if source_type in (p.discovery_capabilities or []))


async def suggest_alert_matrix_templates(
    db: AsyncSession, check_types: set[str]
) -> dict[str, uuid.UUID]:
    """Best matching `AlertMatrixTemplate.id` per check_type, one query for all of them.

    "Best" = system template first, then alphabetical by name — same
    ordering `GET /alerts/matrix-templates/{check_type}` uses, so the id
    surfaced here is whatever a client fetching that list would see first.
    """
    if not check_types:
        return {}
    rows = (
        await db.execute(
            select(AlertMatrixTemplate.check_type, AlertMatrixTemplate.id)
            .where(AlertMatrixTemplate.check_type.in_(check_types))
            .order_by(
                AlertMatrixTemplate.check_type,
                AlertMatrixTemplate.is_system.desc(),
                AlertMatrixTemplate.name,
            )
        )
    ).all()
    out: dict[str, uuid.UUID] = {}
    for check_type, template_id in rows:
        out.setdefault(check_type, template_id)
    return out


def _build_target_url(host: str, port: int | None, check_type: str) -> str:
    """A syntactically valid `http(s)://` URL — the shape `MonitorCreate.url`
    (`AnyHttpUrl`) requires regardless of check_type.

    For `http` it's the real request target (scheme carries meaning: 443/8443
    get `https://`). For every other check_type the probe checkers only ever
    pull the hostname back out of it (`urlparse(config["url"]).hostname`, see
    `probe/whatisup_probe/checkers/{tcp,udp,smtp,dns,ping,domain_expiry}.py`)
    — the real port lives in `tcp_port`/`udp_port`/`smtp_port` instead, so the
    URL itself is a bare `http://{host}` wrapper.
    """
    if check_type == "http":
        if port in (443, 8443):
            return f"https://{host}" if port == 443 else f"https://{host}:{port}"
        if port in (None, 80):
            return f"http://{host}"
        return f"http://{host}:{port}"
    return f"http://{host}"


def default_monitor_fields(service: DiscoveredService, source: DiscoverySource) -> dict:
    """Prefilled `MonitorCreate` fields for accept() — plan D, D-2 §3.

    Only the fields a proposal can meaningfully suggest: name, url,
    check_type, the check-type's port field, and the source's own team scope
    (a monitor created from a team-owned source stays in that team unless the
    caller overrides it). Group/tags are advisory strings on
    `DiscoveredServiceOut` only — they don't map onto real `MonitorGroup`/
    `Tag` ids without a lookup the caller is better placed to do.
    """
    proposal = compute_proposal(service, source.source_type)
    fields: dict = {
        "name": proposal.name,
        "url": _build_target_url(service.host, service.port, proposal.check_type),
        "check_type": proposal.check_type,
        "team_id": source.team_id,
    }
    port_field = _PORT_FIELD_BY_CHECK_TYPE.get(proposal.check_type)
    if port_field is not None:
        fields[port_field] = service.port
    elif proposal.check_type == "dns":
        fields["dns_record_type"] = "A"
    return fields


def port_field_for_check_type(check_type: str) -> str | None:
    """`Monitor` field name (`tcp_port`/`udp_port`/`smtp_port`) carrying the
    port for this check_type, or ``None`` for check_types with no dedicated
    port field. Exposed for `api/v1/discovery.py`: when a caller overrides
    `check_type` at accept time, the prefill's port field no longer applies
    and must be recomputed for the new one from the same observed port."""
    return _PORT_FIELD_BY_CHECK_TYPE.get(check_type)


def monitor_network_target(monitor: Monitor) -> str | None:
    """`proto://host[:port]`, comparable to `DiscoveredService.normalized_target`.

    Returns ``None`` for check_types with no comparable network target (see
    `_NON_MATCHABLE_CHECK_TYPES`) or an unparseable/empty URL.
    """
    if monitor.check_type in _NON_MATCHABLE_CHECK_TYPES:
        return None
    try:
        parsed = urlparse(monitor.url or "")
    except ValueError:
        return None
    host = (parsed.hostname or "").strip().lower()
    if not host:
        return None

    port_field = _PORT_FIELD_BY_CHECK_TYPE.get(monitor.check_type)
    port = getattr(monitor, port_field, None) if port_field else None
    if port is None:
        port = parsed.port
    if port is None:
        port = _SCHEME_DEFAULT_PORTS.get(parsed.scheme)

    proto = "udp" if monitor.check_type == "udp" else "tcp"
    return f"{proto}://{host}:{port}" if port is not None else f"{proto}://{host}"


async def _owner_team_monitor_targets(
    db: AsyncSession, owner_id: uuid.UUID, team_id: uuid.UUID | None
) -> dict[str, uuid.UUID]:
    """`normalized_target -> monitor_id` for every matchable monitor the source's
    owner/team can see — never crosses into another tenant's monitors."""
    clause = Monitor.owner_id == owner_id
    if team_id is not None:
        clause = or_(clause, Monitor.team_id == team_id)
    monitors = (await db.execute(select(Monitor).where(clause))).scalars().all()
    out: dict[str, uuid.UUID] = {}
    for monitor in monitors:
        target = monitor_network_target(monitor)
        if target is not None:
            out.setdefault(target, monitor.id)
    return out


async def _match_new_proposals(
    db: AsyncSession, source: DiscoverySource, seen_targets: set[str]
) -> None:
    """A `proposed` row whose target is already monitored by its owner/team
    is linked (`accepted` + `monitor_id`) instead of surfacing as a proposal
    — plan_discovery.md D-2 §2: "n'est pas proposée (marquer le lien)"."""
    if not seen_targets:
        return
    proposed = (
        (
            await db.execute(
                select(DiscoveredService).where(
                    DiscoveredService.source_id == source.id,
                    DiscoveredService.status == "proposed",
                    DiscoveredService.normalized_target.in_(seen_targets),
                )
            )
        )
        .scalars()
        .all()
    )
    if not proposed:
        return
    target_map = await _owner_team_monitor_targets(db, source.owner_id, source.team_id)
    if not target_map:
        return
    for row in proposed:
        matched_monitor_id = target_map.get(row.normalized_target)
        if matched_monitor_id is not None:
            row.status = "accepted"
            row.monitor_id = matched_monitor_id


async def _handle_disappearances(
    db: AsyncSession, source: DiscoverySource, seen_targets: set[str], now: datetime
) -> None:
    """A target missing from the latest snapshot: a `proposed` row that was
    never acted on is dropped (it'll come back with a fresh `first_seen_at`
    if the target reappears — nothing worth keeping); an `accepted` one's
    monitor is still real, so it flips to `orphaned` instead of vanishing.
    `dismissed` (the refusal is memorised) and already-`orphaned` rows are
    left untouched."""
    missing = (
        (
            await db.execute(
                select(DiscoveredService).where(
                    DiscoveredService.source_id == source.id,
                    DiscoveredService.normalized_target.notin_(seen_targets),
                )
            )
        )
        .scalars()
        .all()
    )
    for row in missing:
        if row.status == "proposed":
            await db.delete(row)
        elif row.status == "accepted":
            row.status = "orphaned"
            row.status_changed_at = now


async def _handle_dismissed_drift(
    db: AsyncSession, source: DiscoverySource, seen_targets: set[str], now: datetime
) -> None:
    """A `dismissed` row still present in this snapshot whose *nature* has
    changed since the refusal — plan D, D-4: "re-proposition quand un service
    refusé change (port/nature)". The port is already baked into
    `normalized_target` (a different port is a different row); what this
    catches is the same target now looking like a different service (a
    docker container redeployed from another image on the same published
    port, for instance).

    Called after `push_discovery`'s upsert loop has already refreshed
    `hints` in place for every target in `seen_targets` — so `service.hints`
    here is the *current* observation, compared against the fingerprint
    frozen at dismiss time. `dismissed_fingerprint is None` (dismissed
    before D-4, or the column was never populated) is left untouched on
    purpose: there is no baseline to compare against, and guessing one would
    silently re-open refusals nobody asked to revisit.
    """
    if not seen_targets:
        return
    dismissed = (
        (
            await db.execute(
                select(DiscoveredService).where(
                    DiscoveredService.source_id == source.id,
                    DiscoveredService.status == "dismissed",
                    DiscoveredService.dismissed_fingerprint.is_not(None),
                    DiscoveredService.normalized_target.in_(seen_targets),
                )
            )
        )
        .scalars()
        .all()
    )
    for row in dismissed:
        if dismissal_fingerprint(row.hints) == row.dismissed_fingerprint:
            continue  # refusal still holds — nothing about the service changed
        row.status = "proposed"
        row.dismissed_reason = None
        row.dismissed_fingerprint = None
        row.status_changed_at = now


async def _handle_reappearances(
    db: AsyncSession, source: DiscoverySource, seen_targets: set[str], now: datetime
) -> None:
    """An `orphaned` row whose target is back in this snapshot: the monitor's
    target reappeared, so it goes back to `accepted` (same monitor_id)."""
    if not seen_targets:
        return
    reappeared = (
        (
            await db.execute(
                select(DiscoveredService).where(
                    DiscoveredService.source_id == source.id,
                    DiscoveredService.status == "orphaned",
                    DiscoveredService.normalized_target.in_(seen_targets),
                )
            )
        )
        .scalars()
        .all()
    )
    for row in reappeared:
        row.status = "accepted"
        row.status_changed_at = now


async def reconcile_source_push(
    db: AsyncSession, source: DiscoverySource, seen_targets: set[str], now: datetime
) -> None:
    """Turn one ingested snapshot into reviewable state (plan D, D-2).

    Called by `push_discovery` right after its upsert loop, before commit —
    `seen_targets` is the exact set of normalized targets in *this* push
    (post intra-payload dedup), scoped entirely to `source.id`. No automatic
    transition here is audit-logged (matching D-1's ingestion, which isn't
    either): these are inventory bookkeeping, not a user action. Manual
    accept/dismiss keep their own audit trail in `api/v1/discovery.py`.
    """
    await _handle_dismissed_drift(db, source, seen_targets, now)
    await _match_new_proposals(db, source, seen_targets)
    await _handle_disappearances(db, source, seen_targets, now)
    await _handle_reappearances(db, source, seen_targets, now)
