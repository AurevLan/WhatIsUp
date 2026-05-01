"""Incident-open → probe diagnostic dispatch (V2-01-01).

When ``services.incident.process_check_result`` opens a new incident, it calls
``enqueue_diagnostic_requests`` which writes one Redis key per affected probe.
The probe drains those keys at its next heartbeat (cf. ``api.v1.probes`` —
``drain_pending_diagnostics``) and runs the requested collectors.

We deliberately reuse the existing trigger-now Redis pattern (transient keys
consumed at heartbeat) instead of introducing a new pub/sub channel — fewer
moving parts, and the at-most-once semantics are acceptable for diagnostics
(if a probe misses one, it will still have its check results in the incident
trail, and a manual retry endpoint can be added later if needed).
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import structlog

from whatisup.core.redis import get_redis

logger = structlog.get_logger(__name__)

_KEY_PREFIX = "whatisup:diag_request"
_TTL_SECONDS = 3600  # 1 h — probe should heartbeat well before this expires
_DEFAULT_KINDS = (
    "traceroute",
    "dig_trace",
    "openssl_handshake",
    "icmp_ping",
    "http_verbose",
)


def _key(incident_id: uuid.UUID, probe_id: uuid.UUID | str) -> str:
    return f"{_KEY_PREFIX}:{incident_id}:{probe_id}"


async def enqueue_diagnostic_requests(
    incident_id: uuid.UUID,
    monitor_id: uuid.UUID,
    target: str,
    check_type: str,
    affected_probe_ids: list[str],
) -> None:
    """Post one diagnostic request per affected probe to Redis.

    Best-effort: a Redis hiccup must not break the incident pipeline, so any
    exception is logged and swallowed."""
    if not affected_probe_ids:
        return
    try:
        redis = get_redis()
        spec = {
            "incident_id": str(incident_id),
            "monitor_id": str(monitor_id),
            "target": target,
            "check_type": check_type,
            "kinds": list(_DEFAULT_KINDS),
        }
        payload = json.dumps(spec)
        async with redis.pipeline(transaction=False) as pipe:
            for pid in affected_probe_ids:
                pipe.set(_key(incident_id, pid), payload, ex=_TTL_SECONDS)
            await pipe.execute()
        logger.info(
            "diagnostic_requests_enqueued",
            incident_id=str(incident_id),
            probe_count=len(affected_probe_ids),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "diagnostic_enqueue_failed",
            incident_id=str(incident_id),
            error=str(exc),
        )


async def drain_pending_diagnostics(probe_id: uuid.UUID) -> list[dict[str, Any]]:
    """Pop and return all pending diagnostic specs for the given probe.

    Returns a list of dicts shaped like ``PendingDiagnostic`` (cf. schema)."""
    try:
        redis = get_redis()
        pattern = f"{_KEY_PREFIX}:*:{probe_id}"
        keys: list[str] = []
        async for key in redis.scan_iter(match=pattern, count=200):
            keys.append(key)
        if not keys:
            return []
        raw_values = await redis.mget(keys)
        # Best-effort cleanup: drop the keys we just read.
        await redis.delete(*keys)
        out: list[dict[str, Any]] = []
        for raw in raw_values:
            if not raw:
                continue
            try:
                out.append(json.loads(raw))
            except json.JSONDecodeError:
                continue
        return out
    except Exception as exc:  # noqa: BLE001
        logger.warning("diagnostic_drain_failed", probe_id=str(probe_id), error=str(exc))
        return []
