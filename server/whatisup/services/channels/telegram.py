"""Telegram alert channel."""

from __future__ import annotations

from typing import Any

import httpx

from ._helpers import scope_label_fr
from .base import BaseAlertChannel


async def _post(config: dict[str, Any], payload: dict[str, Any]) -> str:
    """POST to the Bot API without ever letting the token reach an exception.

    The Bot API only accepts its credential in the URL path, and httpx puts the
    request URL in `HTTPStatusError` — so an ordinary 401/429 used to write the
    plaintext bot_token into the server logs (audit F6). Raise on the status
    code alone instead.
    """
    url = f"https://api.telegram.org/bot{config['bot_token']}/sendMessage"
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(url, json=payload)
    if resp.status_code >= 400:
        raise RuntimeError(f"Telegram API returned HTTP {resp.status_code}")
    return f"HTTP {resp.status_code}"


class TelegramChannel(BaseAlertChannel):
    name = "telegram"

    async def test(self, config: dict[str, Any], settings: Any) -> tuple[bool, str]:
        detail = await _post(
            config,
            {
                "chat_id": config["chat_id"],
                "text": "✅ <b>WhatIsUp — Test de canal</b>\nConnexion Telegram OK.",
                "parse_mode": "HTML",
            },
        )
        return True, detail

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

        return await _post(
            config,
            {"chat_id": config["chat_id"], "text": text, "parse_mode": "HTML"},
        )


def setup(register):
    register(TelegramChannel())
