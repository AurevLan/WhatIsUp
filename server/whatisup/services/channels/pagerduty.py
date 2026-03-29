"""PagerDuty alert channel."""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import structlog

from ._helpers import scope_label_en
from .base import BaseAlertChannel

logger = structlog.get_logger(__name__)


class PagerDutyChannel(BaseAlertChannel):
    name = "pagerduty"

    async def test(self, config: dict[str, Any], settings: Any) -> tuple[bool, str]:
        if not settings.is_production:
            return True, "skipped:non_production (PagerDuty ne s'exécute qu'en production)"
        url = "https://events.pagerduty.com/v2/enqueue"
        payload = {
            "routing_key": config["integration_key"],
            "event_action": "trigger",
            "dedup_key": f"whatisup-test-{uuid.uuid4()}",
            "payload": {
                "summary": "WhatIsUp — Test de canal PagerDuty",
                "severity": config.get("severity", "info"),
                "source": "WhatIsUp",
            },
        }
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json=payload)
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
                "pagerduty_skipped_non_production",
                monitor_name=ctx.get("monitor_name"),
                incident_id=str(incident.id),
            )
            return "skipped:non_production"

        monitor_name = ctx.get("monitor_name", str(incident.monitor_id))
        details = scope_label_en(incident, ctx)
        inc_status = "down" if event_type != "incident_resolved" else "up"

        url = "https://events.pagerduty.com/v2/enqueue"
        event_action = "trigger" if inc_status == "down" else "resolve"
        status_emoji = "🔴" if inc_status == "down" else "✅"
        payload = {
            "routing_key": config["integration_key"],
            "event_action": event_action,
            "dedup_key": f"whatisup-{incident.id}",
            "payload": {
                "summary": f"{status_emoji} {monitor_name}: {details}",
                "severity": config.get("severity", "critical"),
                "source": "WhatIsUp",
            },
        }
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            return f"HTTP {resp.status_code}"


def setup(register):
    register(PagerDutyChannel())
