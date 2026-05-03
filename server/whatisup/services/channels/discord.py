"""Discord alert channel — incoming webhook with embeds."""

from __future__ import annotations

from typing import Any

import httpx

from ._helpers import scope_label_en, validate_webhook_url
from .base import BaseAlertChannel

# Discord embed colors are RGB integers (decimal). 0x36A64F == 3582031 (green),
# 0xDC3545 == 14430533 (red), 0x4F9CF9 == 5217529 (blue).
_COLOR_GREEN = 0x36A64F
_COLOR_RED = 0xDC3545
_COLOR_BLUE = 0x4F9CF9


class DiscordChannel(BaseAlertChannel):
    name = "discord"

    async def test(self, config: dict[str, Any], settings: Any) -> tuple[bool, str]:
        await validate_webhook_url(config["webhook_url"])
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                config["webhook_url"],
                json={
                    "embeds": [
                        {
                            "title": "WhatIsUp — Channel test",
                            "description": "Discord webhook OK.",
                            "color": _COLOR_BLUE,
                            "footer": {"text": "WhatIsUp Monitoring"},
                        }
                    ]
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
        scope = scope_label_en(incident, ctx)

        is_resolved = event_type == "incident_resolved"
        color = _COLOR_GREEN if is_resolved else _COLOR_RED
        status_text = "RESOLVED" if is_resolved else "ALERT"

        fields = [
            {"name": "Monitor", "value": monitor_name, "inline": True},
            {"name": "Type", "value": check_type, "inline": True},
            {"name": "Scope", "value": scope, "inline": False},
            {
                "name": "Started",
                "value": incident.started_at.strftime("%Y-%m-%d %H:%M UTC"),
                "inline": True,
            },
        ]
        if is_resolved and incident.duration_seconds:
            fields.append(
                {"name": "Duration", "value": f"{incident.duration_seconds}s", "inline": True}
            )

        payload = {
            "embeds": [
                {
                    "title": f"WhatIsUp — {status_text}",
                    "color": color,
                    "fields": fields,
                    "footer": {"text": "WhatIsUp Monitoring"},
                    "timestamp": incident.started_at.isoformat(),
                }
            ]
        }

        await validate_webhook_url(config["webhook_url"])
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(config["webhook_url"], json=payload)
            resp.raise_for_status()
            return f"HTTP {resp.status_code}"


def setup(register):
    register(DiscordChannel())
