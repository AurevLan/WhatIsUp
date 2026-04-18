"""Webhook alert channel."""

from __future__ import annotations

import hashlib
import hmac
import json
import string
from datetime import UTC, datetime
from typing import Any

import httpx

from ._helpers import validate_webhook_url
from .base import BaseAlertChannel


class WebhookChannel(BaseAlertChannel):
    name = "webhook"

    async def test(self, config: dict[str, Any], settings: Any) -> tuple[bool, str]:
        await validate_webhook_url(config["url"])
        payload = {
            "event": "test",
            "message": "WhatIsUp — test de canal",
            "timestamp": datetime.now(UTC).isoformat(),
        }
        payload_bytes = json.dumps(payload).encode()
        headers = {"Content-Type": "application/json", "User-Agent": "WhatIsUp/1.0"}
        if secret := config.get("secret"):
            sig = hmac.new(secret.encode(), payload_bytes, hashlib.sha256).hexdigest()
            headers["X-WhatIsUp-Signature"] = f"sha256={sig}"
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(config["url"], content=payload_bytes, headers=headers)
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
        await validate_webhook_url(config["url"])
        probe_names = ctx.get("probe_names", {})
        enriched_event_type = "incident.resolved" if incident.resolved_at else "incident.opened"
        monitor_name = ctx.get("monitor_name", str(incident.monitor_id))
        monitor_url = ctx.get("monitor_url")
        check_type = ctx.get("check_type", "unknown")
        # Template variables available for custom webhook templates
        template_vars = {
            "monitor_name": monitor_name,
            "monitor_id": str(incident.monitor_id),
            "check_type": check_type,
            "status": "resolved" if incident.resolved_at else "down",
            "started_at": incident.started_at.isoformat() if incident.started_at else "",
            "resolved_at": incident.resolved_at.isoformat() if incident.resolved_at else "",
            "duration": str(incident.duration_seconds or 0),
            "scope": incident.scope.value,
            "event_type": enriched_event_type,
        }

        # Check for custom webhook template on the channel model
        webhook_tpl = getattr(channel, "webhook_template", None)
        if webhook_tpl:
            tpl = string.Template(webhook_tpl)
            rendered = tpl.safe_substitute(template_vars)
            payload_bytes = rendered.encode()
            # Detect content type: if it looks like JSON, use application/json
            stripped = rendered.strip()
            content_type = "application/json" if stripped.startswith(("{", "[")) else "text/plain"
        else:
            payload = {
                # Legacy fields (backward compatibility)
                "event": event_type,
                "monitor_id": str(incident.monitor_id),
                "monitor_name": monitor_name,
                "check_type": check_type,
                "incident_id": str(incident.id),
                "scope": incident.scope.value,
                "affected_probes": [
                    {"id": pid, "name": probe_names.get(pid, pid)}
                    for pid in (incident.affected_probe_ids or [])
                ],
                "started_at": incident.started_at.isoformat(),
                "resolved_at": incident.resolved_at.isoformat() if incident.resolved_at else None,
                "duration_seconds": incident.duration_seconds,
                "timestamp": datetime.now(UTC).isoformat(),
                # Enriched structured payload
                "event_type": enriched_event_type,
                "monitor": {
                    "id": str(incident.monitor_id),
                    "name": monitor_name,
                    "url": monitor_url,
                    "check_type": check_type,
                },
                "incident": {
                    "id": str(incident.id),
                    "started_at": incident.started_at.isoformat() if incident.started_at else None,
                    "resolved_at": (
                        incident.resolved_at.isoformat() if incident.resolved_at else None
                    ),
                    "scope": incident.scope.value,
                },
            }
            payload_bytes = json.dumps(payload).encode()
            content_type = "application/json"

        headers = {
            "Content-Type": content_type,
            "User-Agent": "WhatIsUp/1.0",
            "X-WhatIsUp-Event": enriched_event_type,
        }
        if secret := config.get("secret"):
            sig = hmac.new(secret.encode(), payload_bytes, hashlib.sha256).hexdigest()
            headers["X-WhatIsUp-Signature"] = f"sha256={sig}"

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(config["url"], content=payload_bytes, headers=headers)
            resp.raise_for_status()
            return f"HTTP {resp.status_code}"


def setup(register):
    register(WebhookChannel())
