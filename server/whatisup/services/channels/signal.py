"""Signal REST API alert channel.

Sends alerts via a signal-cli REST API instance.
API docs: https://bbernhard.github.io/signal-cli-rest-api/
"""

from __future__ import annotations

from typing import Any

import httpx

from ._helpers import scope_label_fr, validate_webhook_url
from .base import BaseAlertChannel


class SignalChannel(BaseAlertChannel):
    name = "signal"

    async def test(self, config: dict[str, Any], settings: Any) -> tuple[bool, str]:
        api_url = config["api_url"].rstrip("/")
        await validate_webhook_url(api_url)

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{api_url}/v2/send",
                json={
                    "message": "✅ WhatIsUp — Test de canal Signal OK.",
                    "number": config["sender_number"],
                    "recipients": config["recipients"],
                },
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
        monitor_name = ctx.get("monitor_name", str(incident.monitor_id))
        check_type = ctx.get("check_type", "?").upper()
        scope = scope_label_fr(incident, ctx)

        is_resolved = event_type == "incident_resolved"
        status_emoji = "✅" if is_resolved else "🔴"

        lines = [
            f"{status_emoji} WhatIsUp — {scope}",
            f"Monitor : {monitor_name}",
            f"Type : {check_type}",
            f"Début : {incident.started_at.strftime('%Y-%m-%d %H:%M UTC')}",
        ]
        if is_resolved and incident.resolved_at:
            lines.append(f"Résolu : {incident.resolved_at.strftime('%Y-%m-%d %H:%M UTC')}")
            if incident.duration_seconds:
                lines.append(f"Durée : {incident.duration_seconds}s")

        message = "\n".join(lines)

        api_url = config["api_url"].rstrip("/")
        await validate_webhook_url(api_url)

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{api_url}/v2/send",
                json={
                    "message": message,
                    "number": config["sender_number"],
                    "recipients": config["recipients"],
                },
            )
            resp.raise_for_status()
            return f"HTTP {resp.status_code}"


def setup(register):
    register(SignalChannel())
