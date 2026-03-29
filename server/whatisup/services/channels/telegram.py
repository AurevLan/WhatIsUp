"""Telegram alert channel."""

from __future__ import annotations

from typing import Any

import httpx

from ._helpers import scope_label_fr
from .base import BaseAlertChannel


class TelegramChannel(BaseAlertChannel):
    name = "telegram"

    async def test(self, config: dict[str, Any], settings: Any) -> tuple[bool, str]:
        url = f"https://api.telegram.org/bot{config['bot_token']}/sendMessage"
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                url,
                json={
                    "chat_id": config["chat_id"],
                    "text": "✅ <b>WhatIsUp — Test de canal</b>\nConnexion Telegram OK.",
                    "parse_mode": "HTML",
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
            f"{status_emoji} <b>WhatIsUp — {scope}</b>",
            f"<b>Monitor :</b> {monitor_name}",
            f"<b>Type :</b> {check_type}",
            f"<b>Début :</b> {incident.started_at.strftime('%Y-%m-%d %H:%M UTC')}",
        ]
        if is_resolved and incident.resolved_at:
            lines.append(f"<b>Résolu :</b> {incident.resolved_at.strftime('%Y-%m-%d %H:%M UTC')}")
            if incident.duration_seconds:
                lines.append(f"<b>Durée :</b> {incident.duration_seconds}s")

        text = "\n".join(lines)

        url = f"https://api.telegram.org/bot{config['bot_token']}/sendMessage"
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                url,
                json={"chat_id": config["chat_id"], "text": text, "parse_mode": "HTML"},
            )
            resp.raise_for_status()
            return f"HTTP {resp.status_code}"


def setup(register):
    register(TelegramChannel())
