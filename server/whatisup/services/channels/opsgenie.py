"""Opsgenie alert channel."""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import structlog

from ._helpers import scope_label_en
from .base import BaseAlertChannel

logger = structlog.get_logger(__name__)


class OpsgenieChannel(BaseAlertChannel):
    name = "opsgenie"

    async def test(self, config: dict[str, Any], settings: Any) -> tuple[bool, str]:
        if not settings.is_production:
            return True, "skipped:non_production (Opsgenie ne s'exécute qu'en production)"
        region = config.get("region", "us")
        base_url = "https://api.opsgenie.com" if region == "us" else "https://api.eu.opsgenie.com"
        headers = {"Authorization": f"GenieKey {config['api_key']}"}
        payload = {
            "message": "WhatIsUp — Test de canal Opsgenie",
            "alias": f"whatisup-test-{uuid.uuid4()}",
            "priority": "P5",
            "source": "WhatIsUp",
        }
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{base_url}/v2/alerts", json=payload, headers=headers
            )
            resp.raise_for_status()
            return True, f"HTTP {resp.status_code}"

    async def send(
        self,
        incident: Any,
        channel: Any,
        event_type: str,
        ctx: dict[str, Any],
        config: dict[str, Any],
        settings: Any,
    ) -> str | None:
        if not settings.is_production:
            logger.debug(
                "opsgenie_skipped_non_production",
                monitor_name=ctx.get("monitor_name"),
                incident_id=str(incident.id),
            )
            return "skipped:non_production"

        monitor_name = ctx.get("monitor_name", str(incident.monitor_id))
        details = scope_label_en(incident, ctx)
        inc_status = "down" if event_type != "incident_resolved" else "up"

        region = config.get("region", "us")
        base_url = "https://api.opsgenie.com" if region == "us" else "https://api.eu.opsgenie.com"
        headers = {"Authorization": f"GenieKey {config['api_key']}"}

        if inc_status == "down":
            url = f"{base_url}/v2/alerts"
            payload = {
                "message": f"{monitor_name}: {details}",
                "alias": f"whatisup-{incident.id}",
                "priority": config.get("priority", "P1"),
                "source": "WhatIsUp",
            }
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                return f"HTTP {resp.status_code}"
        else:
            url = f"{base_url}/v2/alerts/whatisup-{incident.id}/close"
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(url, json={"source": "WhatIsUp"}, headers=headers)
                resp.raise_for_status()
                return f"HTTP {resp.status_code}"


def setup(register):
    register(OpsgenieChannel())
