"""Microsoft Teams alert channel — Power Automate workflow webhook with Adaptive Card."""

from __future__ import annotations

from typing import Any

import httpx

from ._helpers import scope_label_en, validate_webhook_url
from .base import BaseAlertChannel


def _adaptive_card(title: str, color_style: str, facts: list[dict[str, str]]) -> dict[str, Any]:
    """Build an Adaptive Card v1.5 payload.

    color_style: "good" (green), "warning" (orange), "attention" (red), "default".
    """
    return {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.5",
        "body": [
            {
                "type": "TextBlock",
                "size": "Large",
                "weight": "Bolder",
                "text": title,
                "color": color_style,
                "wrap": True,
            },
            {"type": "FactSet", "facts": facts},
        ],
    }


class TeamsChannel(BaseAlertChannel):
    name = "teams"

    async def test(self, config: dict[str, Any], settings: Any) -> tuple[bool, str]:
        await validate_webhook_url(config["webhook_url"])
        card = _adaptive_card(
            "WhatIsUp — Channel test",
            "default",
            [{"title": "Status", "value": "Teams webhook OK"}],
        )
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                config["webhook_url"],
                json={
                    "type": "message",
                    "attachments": [
                        {
                            "contentType": "application/vnd.microsoft.card.adaptive",
                            "content": card,
                        }
                    ],
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
        color_style = "good" if is_resolved else "attention"
        status_text = "RESOLVED" if is_resolved else "ALERT"

        facts = [
            {"title": "Monitor", "value": monitor_name},
            {"title": "Type", "value": check_type},
            {"title": "Scope", "value": scope},
            {
                "title": "Started",
                "value": incident.started_at.strftime("%Y-%m-%d %H:%M UTC"),
            },
        ]
        if is_resolved and incident.duration_seconds:
            facts.append({"title": "Duration", "value": f"{incident.duration_seconds}s"})

        card = _adaptive_card(f"WhatIsUp — {status_text}", color_style, facts)
        payload = {
            "type": "message",
            "attachments": [
                {
                    "contentType": "application/vnd.microsoft.card.adaptive",
                    "content": card,
                }
            ],
        }

        await validate_webhook_url(config["webhook_url"])
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(config["webhook_url"], json=payload)
            resp.raise_for_status()
            return f"HTTP {resp.status_code}"


def setup(register):
    register(TeamsChannel())
