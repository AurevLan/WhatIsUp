"""Email alert channel."""

from __future__ import annotations

from email.message import EmailMessage
from typing import Any

import aiosmtplib

from ._helpers import scope_label_fr
from .base import BaseAlertChannel


class EmailChannel(BaseAlertChannel):
    name = "email"

    async def test(self, config: dict[str, Any], settings: Any) -> tuple[bool, str]:
        msg = EmailMessage()
        msg["From"] = str(settings.smtp_from)
        msg["To"] = ", ".join(config["to"])
        msg["Subject"] = "[WhatIsUp] Test de canal — connexion OK"
        msg.set_content(
            "Ceci est un message de test envoyé depuis WhatIsUp.\n"
            "Si vous recevez ce message, votre canal email est correctement configuré."
        )
        await aiosmtplib.send(
            msg,
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            start_tls=settings.smtp_tls,
            username=settings.smtp_user or None,
            password=settings.smtp_password or None,
            timeout=15,
        )
        return True, f"Email envoyé à : {', '.join(config['to'])}"

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
        check_type = ctx.get("check_type", "?")
        scope = scope_label_fr(incident, ctx)

        is_resolved = event_type == "incident_resolved"
        subject = (
            f"[WhatIsUp] {'RÉSOLU' if is_resolved else 'ALERTE'}: "
            f"{monitor_name} ({check_type.upper()}) — {scope}"
        )
        body = _build_email_body(incident, event_type, monitor_name, check_type, ctx)

        msg = EmailMessage()
        msg["From"] = str(settings.smtp_from)
        msg["To"] = ", ".join(config["to"])
        msg["Subject"] = subject
        msg.set_content(body, subtype="html")

        await aiosmtplib.send(
            msg,
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            start_tls=settings.smtp_tls,
            username=settings.smtp_user or None,
            password=settings.smtp_password or None,
            timeout=15,
        )
        return None


def _build_email_body(
    incident: Any,
    event_type: str,
    monitor_name: str,
    check_type: str,
    ctx: dict,
) -> str:
    status_emoji = "✅" if event_type == "incident_resolved" else "🔴"
    scope = scope_label_fr(incident, ctx)
    resolved_line = ""
    if incident.resolved_at:
        resolved_line = (
            f"<p><b>Résolu le :</b> {incident.resolved_at.strftime('%Y-%m-%d %H:%M:%S UTC')}</p>"
        )
        if incident.duration_seconds:
            resolved_line += f"<p><b>Durée :</b> {incident.duration_seconds}s</p>"

    return f"""
    <html><body style="font-family: sans-serif; color: #333;">
    <h2>{status_emoji} WhatIsUp — {scope}</h2>
    <p><b>Monitor :</b> {monitor_name}</p>
    <p><b>Type :</b> {check_type.upper()}</p>
    <p><b>Début :</b> {incident.started_at.strftime("%Y-%m-%d %H:%M:%S UTC")}</p>
    {resolved_line}
    <hr><p style="color:#888; font-size:12px;">WhatIsUp Monitoring</p>
    </body></html>
    """


def setup(register):
    register(EmailChannel())
