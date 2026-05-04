"""V2-02-05 — BGP looking-glass via RIPEstat data API.

Returns AS-paths observed from multiple RIPE NCC RRC vantage points for the
target IP of an incident. Cached 60 s in Redis to keep the upstream load low.
"""

from __future__ import annotations

import json
import socket
import uuid
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.api.deps import get_current_user
from whatisup.core.database import get_db
from whatisup.core.limiter import limiter
from whatisup.core.redis import get_redis
from whatisup.models.incident import Incident
from whatisup.models.monitor import Monitor
from whatisup.models.user import User

router = APIRouter(prefix="/incidents", tags=["bgp"])

_CACHE_TTL_SEC = 60
_RIPESTAT_URL = "https://stat.ripe.net/data/looking-glass/data.json"
_VALID_VERDICTS = {"network_partition_asn", "network_partition_geo"}


def _resolve_ip(host: str) -> str | None:
    """Best-effort hostname → IP resolution (sync, in-process; caller is async route)."""
    try:
        return socket.gethostbyname(host)
    except Exception:
        return None


def _parse_ripestat(payload: dict) -> list[dict]:
    """Flatten RIPEstat looking-glass response into ``[{rrc, peer_asn, as_path}]``."""
    out: list[dict] = []
    rrcs = (payload.get("data") or {}).get("rrcs") or []
    for rrc in rrcs:
        rrc_id = rrc.get("rrc")
        for peer in rrc.get("peers") or []:
            out.append(
                {
                    "rrc": rrc_id,
                    "location": rrc.get("location"),
                    "peer_asn": peer.get("asn_origin"),
                    "as_path": peer.get("as_path"),
                    "prefix": peer.get("prefix"),
                }
            )
    return out


@router.get("/{incident_id}/bgp")
@limiter.limit("20/minute")
async def get_bgp_paths(
    request: Request,
    incident_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Fetch AS-paths to the incident target from multiple BGP vantage points.

    Only available on incidents with a ``network_partition_*`` verdict — for
    plain service outages, BGP path is rarely the right diagnostic.
    """
    incident = (
        await db.execute(
            select(Incident, Monitor.url)
            .join(Monitor, Monitor.id == Incident.monitor_id)
            .where(Incident.id == incident_id, Monitor.owner_id == current_user.id)
        )
    ).first()
    if not incident:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incident not found")

    inc, url = incident
    if inc.network_verdict not in _VALID_VERDICTS:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "BGP looking-glass is only available on incidents with a network_partition_* "
                f"verdict (current: {inc.network_verdict!r})."
            ),
        )

    host = urlparse(url).hostname or url
    target_ip = _resolve_ip(host)
    if not target_ip:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Could not resolve incident target {host!r} to an IP",
        )

    redis = await get_redis()
    cache_key = f"bgp:lg:{target_ip}"
    cached = await redis.get(cache_key)
    if cached:
        return {"target_ip": target_ip, "cached": True, **json.loads(cached)}

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(_RIPESTAT_URL, params={"resource": target_ip})
            resp.raise_for_status()
            payload = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"BGP looking-glass upstream failed: {type(exc).__name__}",
        ) from exc

    paths = _parse_ripestat(payload)
    body = {"paths": paths, "rrc_count": len({p["rrc"] for p in paths})}
    await redis.setex(cache_key, _CACHE_TTL_SEC, json.dumps(body))
    return {"target_ip": target_ip, "cached": False, **body}
