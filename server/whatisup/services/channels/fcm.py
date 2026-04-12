"""FCM (Firebase Cloud Messaging) alert channel — native push for Capacitor app.

Configuration is intentionally minimal: an FCM channel has no per-channel
secret to enter, it just signals "send to my registered mobile devices".
The dispatcher loads the device tokens of the channel owner from the
``device_tokens`` table at send time and pushes via the FCM HTTP v1 API.

Payloads are encrypted per-device with a Fernet key generated at registration
so Google's relay never sees the monitor name in plaintext.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from whatisup.core.database import get_session_factory
from whatisup.models.alert import AlertChannel
from whatisup.models.device_token import DeviceToken
from whatisup.services import fcm

from ._helpers import scope_label_fr
from .base import BaseAlertChannel


async def _devices_for_owner(owner_id) -> list[tuple[str, str]]:
    async with get_session_factory()() as db:
        rows = (
            await db.execute(
                select(DeviceToken.token, DeviceToken.encryption_key).where(
                    DeviceToken.user_id == owner_id
                )
            )
        ).all()
        return [(r.token, r.encryption_key) for r in rows]


async def _prune_invalid(invalid_tokens: list[str]) -> None:
    if not invalid_tokens:
        return
    from sqlalchemy import delete

    async with get_session_factory()() as db:
        await db.execute(delete(DeviceToken).where(DeviceToken.token.in_(invalid_tokens)))
        await db.commit()


class FcmChannel(BaseAlertChannel):
    name = "fcm"

    async def test(self, config: dict[str, Any], settings: Any) -> tuple[bool, str]:
        if not fcm.is_enabled():
            return False, "FCM service account not configured on the server"
        # Test does not have an owner context here — emit a no-op success since
        # the dispatcher will fall back to per-owner device lookup at send time.
        return True, "FCM service account loaded"

    async def send(
        self,
        incident: Any,
        channel: AlertChannel,
        event_type: str,
        ctx: dict[str, Any],
        config: dict[str, Any],
        settings: Any,
    ) -> str | None:
        if not fcm.is_enabled():
            return "fcm:disabled"

        devices = await _devices_for_owner(channel.owner_id)
        if not devices:
            return "fcm:no_devices"

        monitor_name = ctx.get("monitor_name", str(incident.monitor_id))
        check_type = ctx.get("check_type", "?")
        scope = scope_label_fr(incident, ctx)
        is_resolved = event_type == "incident_resolved"

        title = f"{'✅' if is_resolved else '🔴'} {monitor_name}"
        body_lines = [scope, f"Type: {check_type}"]
        if is_resolved and incident.duration_seconds:
            body_lines.append(f"Durée: {incident.duration_seconds}s")

        payload = {
            "title": title,
            "body": " · ".join(body_lines),
            "monitor_id": str(incident.monitor_id),
            "incident_id": str(incident.id),
            "event_type": event_type,
            "resolved": is_resolved,
        }

        result = await fcm.send_to_devices(devices, payload)
        await _prune_invalid(result.get("invalid_tokens", []))
        return f"fcm:sent={result['sent']} failed={result['failed']}"


def setup(register):
    register(FcmChannel())
