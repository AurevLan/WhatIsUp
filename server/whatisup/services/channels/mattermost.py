"""Mattermost alert channel — incoming webhook (Slack-compatible payload)."""

from __future__ import annotations

from typing import Any

import httpx

from ._helpers import scope_label_en, validate_webhook_url
from .base import BaseAlertChannel


class MattermostChannel(BaseAlertChannel):
    name = "mattermost"

    async def test(self, config: dict[str, Any], settings: Any) -> tuple[bool, str]:
        await validate_webhook_url(config["webhook_url"])
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                config["webhook_url"],
                json={
                    "username": "WhatIsUp",
                    "icon_emoji": ":satellite:",
                    "text": "WhatIsUp — Channel test (Mattermost OK).",
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
        color = "#36a64f" if is_resolved else "#dc3545"
        status_text = "RESOLVED" if is_resolved else "ALERT"

        fields = [
            {"title": "Monitor", "value": monitor_name, "short": True},
            {"title": "Type", "value": check_type, "short": True},
            {"title": "Scope", "value": scope, "short": False},
            {
                "title": "Started",
                "value": incident.started_at.strftime("%Y-%m-%d %H:%M UTC"),
                "short": True,
            },
        ]
        if is_resolved and incident.duration_seconds:
            fields.append(
                {"title": "Duration", "value": f"{incident.duration_seconds}s", "short": True}
            )

        payload = {
            "username": "WhatIsUp",
            "icon_emoji": ":satellite:",
            "attachments": [
                {
                    "color": color,
                    "title": f"WhatIsUp — {status_text}",
                    "fields": fields,
                    "footer": "WhatIsUp Monitoring",
                    "ts": int(incident.started_at.timestamp()),
                }
            ],
        }

        await validate_webhook_url(config["webhook_url"])
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(config["webhook_url"], json=payload)
            resp.raise_for_status()
            return f"HTTP {resp.status_code}"


def setup(register):
    register(MattermostChannel())
