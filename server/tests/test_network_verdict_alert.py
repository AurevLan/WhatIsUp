"""plan_cap_v2 §3a — the alert body must say when the network verdict is a
network partition (network_partition_asn / _geo): "the promise of the product
kept at the moment it matters". `service_down` stays implicit (the alert
already says the service is down) and `inconclusive` — like a null verdict —
must add nothing: silence beats a sentence that teaches nothing.

Covers every text-ish channel in `services/channels/`, following the registry
convention (services/alert.py never special-cases a channel type).
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from whatisup.models.incident import IncidentScope
from whatisup.services.channels.discord import DiscordChannel
from whatisup.services.channels.email import _build_email_body
from whatisup.services.channels.fcm import FcmChannel
from whatisup.services.channels.mattermost import MattermostChannel
from whatisup.services.channels.opsgenie import OpsgenieChannel
from whatisup.services.channels.pagerduty import PagerDutyChannel
from whatisup.services.channels.signal import SignalChannel
from whatisup.services.channels.slack import SlackChannel
from whatisup.services.channels.teams import TeamsChannel
from whatisup.services.channels.telegram import TelegramChannel
from whatisup.services.channels.webhook import WebhookChannel

CTX = {"monitor_name": "korben.info", "check_type": "http", "probe_names": {}}

# Fragments unique enough to prove the *right* sentence made it through,
# without pinning the whole wording in every test.
_FR_ASN_FRAGMENT = "opérateur"
_FR_GEO_FRAGMENT = "régional"
_EN_ASN_FRAGMENT = "carrier-side"
_EN_GEO_FRAGMENT = "regional"

_PARTITIONS = ["network_partition_asn", "network_partition_geo"]
_NON_PARTITIONS = ["service_down", "inconclusive", None]


def _incident(verdict: str | None, **overrides) -> SimpleNamespace:
    base = dict(
        id=uuid.uuid4(),
        monitor_id=uuid.uuid4(),
        started_at=datetime(2026, 5, 3, 12, 0, 0, tzinfo=UTC),
        resolved_at=None,
        duration_seconds=None,
        affected_probe_ids=[],
        scope=IncidentScope.global_,
        acked_at=None,
        network_verdict=verdict,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


class _Resp:
    status_code = 200

    def raise_for_status(self) -> None:
        return None


def _patch_http(monkeypatch) -> dict:
    captured: dict = {}

    async def _fake_post(self, url, json=None, content=None, headers=None, **_kw):
        captured["url"] = url
        captured["json"] = json
        captured["content"] = content
        return _Resp()

    monkeypatch.setattr("httpx.AsyncClient.post", _fake_post)
    for mod in (
        "whatisup.services.channels.webhook",
        "whatisup.services.channels.discord",
        "whatisup.services.channels.mattermost",
        "whatisup.services.channels.teams",
        "whatisup.services.channels.slack",
        "whatisup.services.channels.signal",
    ):
        monkeypatch.setattr(f"{mod}.validate_webhook_url", AsyncMock(return_value=None))
    return captured


# ── Slack / Discord / Mattermost / Teams — a dedicated "Network" field ────────


@pytest.mark.asyncio
@pytest.mark.parametrize("verdict", _PARTITIONS)
async def test_slack_mentions_network_verdict_for_partitions(monkeypatch, verdict) -> None:
    captured = _patch_http(monkeypatch)
    await SlackChannel().send(
        _incident(verdict), None, "incident_opened", CTX, {"webhook_url": "https://h/x"}, None
    )
    fields = {f["title"]: f["value"] for f in captured["json"]["attachments"][0]["fields"]}
    assert "Network" in fields
    frag = _EN_ASN_FRAGMENT if verdict == "network_partition_asn" else _EN_GEO_FRAGMENT
    assert frag in fields["Network"]


@pytest.mark.asyncio
@pytest.mark.parametrize("verdict", _NON_PARTITIONS)
async def test_slack_silent_for_non_partitions(monkeypatch, verdict) -> None:
    captured = _patch_http(monkeypatch)
    await SlackChannel().send(
        _incident(verdict), None, "incident_opened", CTX, {"webhook_url": "https://h/x"}, None
    )
    fields = {f["title"]: f["value"] for f in captured["json"]["attachments"][0]["fields"]}
    assert "Network" not in fields


@pytest.mark.asyncio
async def test_discord_mentions_network_verdict(monkeypatch) -> None:
    captured = _patch_http(monkeypatch)
    await DiscordChannel().send(
        _incident("network_partition_asn"),
        None,
        "incident_opened",
        CTX,
        {"webhook_url": "https://h/x"},
        None,
    )
    fields = {f["name"]: f["value"] for f in captured["json"]["embeds"][0]["fields"]}
    assert _EN_ASN_FRAGMENT in fields["Network"]


@pytest.mark.asyncio
async def test_discord_silent_for_service_down(monkeypatch) -> None:
    captured = _patch_http(monkeypatch)
    await DiscordChannel().send(
        _incident("service_down"),
        None,
        "incident_opened",
        CTX,
        {"webhook_url": "https://h/x"},
        None,
    )
    names = [f["name"] for f in captured["json"]["embeds"][0]["fields"]]
    assert "Network" not in names


@pytest.mark.asyncio
async def test_mattermost_mentions_network_verdict(monkeypatch) -> None:
    captured = _patch_http(monkeypatch)
    await MattermostChannel().send(
        _incident("network_partition_geo"),
        None,
        "incident_opened",
        CTX,
        {"webhook_url": "https://h/x"},
        None,
    )
    fields = {f["title"]: f["value"] for f in captured["json"]["attachments"][0]["fields"]}
    assert _EN_GEO_FRAGMENT in fields["Network"]


@pytest.mark.asyncio
async def test_mattermost_silent_for_inconclusive(monkeypatch) -> None:
    captured = _patch_http(monkeypatch)
    await MattermostChannel().send(
        _incident("inconclusive"),
        None,
        "incident_opened",
        CTX,
        {"webhook_url": "https://h/x"},
        None,
    )
    titles = [f["title"] for f in captured["json"]["attachments"][0]["fields"]]
    assert "Network" not in titles


@pytest.mark.asyncio
async def test_teams_mentions_network_verdict(monkeypatch) -> None:
    captured = _patch_http(monkeypatch)
    await TeamsChannel().send(
        _incident("network_partition_asn"),
        None,
        "incident_opened",
        CTX,
        {"webhook_url": "https://h/x"},
        None,
    )
    facts = {
        f["title"]: f["value"]
        for f in captured["json"]["attachments"][0]["content"]["body"][1]["facts"]
    }
    assert _EN_ASN_FRAGMENT in facts["Network"]


@pytest.mark.asyncio
async def test_teams_silent_for_service_down(monkeypatch) -> None:
    captured = _patch_http(monkeypatch)
    await TeamsChannel().send(
        _incident("service_down"),
        None,
        "incident_opened",
        CTX,
        {"webhook_url": "https://h/x"},
        None,
    )
    titles = [f["title"] for f in captured["json"]["attachments"][0]["content"]["body"][1]["facts"]]
    assert "Network" not in titles


# ── Telegram / Signal / FCM — plain-text body (French) ────────────────────────


@pytest.mark.asyncio
async def test_telegram_mentions_network_verdict(monkeypatch) -> None:
    captured = _patch_http(monkeypatch)
    await TelegramChannel().send(
        _incident("network_partition_asn"),
        None,
        "incident_opened",
        CTX,
        {"bot_token": "x:y", "chat_id": "1"},
        None,
    )
    assert _FR_ASN_FRAGMENT in captured["json"]["text"]


@pytest.mark.asyncio
async def test_telegram_silent_for_inconclusive(monkeypatch) -> None:
    captured = _patch_http(monkeypatch)
    await TelegramChannel().send(
        _incident("inconclusive"),
        None,
        "incident_opened",
        CTX,
        {"bot_token": "x:y", "chat_id": "1"},
        None,
    )
    assert "Réseau" not in captured["json"]["text"]


@pytest.mark.asyncio
async def test_signal_mentions_network_verdict(monkeypatch) -> None:
    captured = _patch_http(monkeypatch)
    await SignalChannel().send(
        _incident("network_partition_geo"),
        None,
        "incident_opened",
        CTX,
        {"api_url": "https://h", "sender_number": "+1", "recipients": ["+2"]},
        None,
    )
    assert _FR_GEO_FRAGMENT in captured["json"]["message"]


@pytest.mark.asyncio
async def test_signal_silent_for_service_down(monkeypatch) -> None:
    captured = _patch_http(monkeypatch)
    await SignalChannel().send(
        _incident("service_down"),
        None,
        "incident_opened",
        CTX,
        {"api_url": "https://h", "sender_number": "+1", "recipients": ["+2"]},
        None,
    )
    assert "Réseau" not in captured["json"]["message"]


@pytest.mark.asyncio
async def test_fcm_mentions_network_verdict(monkeypatch) -> None:
    monkeypatch.setattr("whatisup.services.channels.fcm.fcm.is_enabled", lambda: True)
    monkeypatch.setattr(
        "whatisup.services.channels.fcm._devices_for_owner",
        AsyncMock(return_value=[("token1", "key1")]),
    )
    sent = AsyncMock(return_value={"sent": 1, "failed": 0, "invalid_tokens": []})
    monkeypatch.setattr("whatisup.services.channels.fcm.fcm.send_to_devices", sent)

    incident = _incident("network_partition_asn")
    channel = SimpleNamespace(owner_id=uuid.uuid4())
    await FcmChannel().send(incident, channel, "incident_opened", CTX, {}, None)

    payload = sent.call_args.args[1]
    assert _FR_ASN_FRAGMENT in payload["body"]


@pytest.mark.asyncio
async def test_fcm_silent_for_inconclusive(monkeypatch) -> None:
    monkeypatch.setattr("whatisup.services.channels.fcm.fcm.is_enabled", lambda: True)
    monkeypatch.setattr(
        "whatisup.services.channels.fcm._devices_for_owner",
        AsyncMock(return_value=[("token1", "key1")]),
    )
    sent = AsyncMock(return_value={"sent": 1, "failed": 0, "invalid_tokens": []})
    monkeypatch.setattr("whatisup.services.channels.fcm.fcm.send_to_devices", sent)

    incident = _incident("inconclusive")
    channel = SimpleNamespace(owner_id=uuid.uuid4())
    await FcmChannel().send(incident, channel, "incident_opened", CTX, {}, None)

    payload = sent.call_args.args[1]
    assert "Réseau" not in payload["body"]


# ── PagerDuty / Opsgenie — production-only, structured fields ────────────────


@pytest.mark.asyncio
async def test_pagerduty_mentions_network_verdict(monkeypatch) -> None:
    captured = _patch_http(monkeypatch)
    settings = SimpleNamespace(is_production=True)
    await PagerDutyChannel().send(
        _incident("network_partition_asn"),
        None,
        "incident_opened",
        CTX,
        {"integration_key": "k"},
        settings,
    )
    details = captured["json"]["payload"].get("custom_details")
    assert details is not None
    assert _EN_ASN_FRAGMENT in details["network"]


@pytest.mark.asyncio
async def test_pagerduty_silent_for_service_down(monkeypatch) -> None:
    captured = _patch_http(monkeypatch)
    settings = SimpleNamespace(is_production=True)
    await PagerDutyChannel().send(
        _incident("service_down"),
        None,
        "incident_opened",
        CTX,
        {"integration_key": "k"},
        settings,
    )
    assert "custom_details" not in captured["json"]["payload"]


@pytest.mark.asyncio
async def test_opsgenie_mentions_network_verdict(monkeypatch) -> None:
    captured = _patch_http(monkeypatch)
    settings = SimpleNamespace(is_production=True)
    await OpsgenieChannel().send(
        _incident("network_partition_geo"),
        None,
        "incident_opened",
        CTX,
        {"api_key": "x"},
        settings,
    )
    assert _EN_GEO_FRAGMENT in captured["json"]["description"]


@pytest.mark.asyncio
async def test_opsgenie_silent_for_inconclusive(monkeypatch) -> None:
    captured = _patch_http(monkeypatch)
    settings = SimpleNamespace(is_production=True)
    await OpsgenieChannel().send(
        _incident("inconclusive"),
        None,
        "incident_opened",
        CTX,
        {"api_key": "x"},
        settings,
    )
    assert "description" not in captured["json"]


# ── Webhook — structured JSON, both legacy and enriched shapes ────────────────


@pytest.mark.asyncio
async def test_webhook_mentions_network_verdict(monkeypatch) -> None:
    captured = _patch_http(monkeypatch)
    await WebhookChannel().send(
        _incident("network_partition_asn"),
        SimpleNamespace(webhook_template=None),
        "incident_opened",
        CTX,
        {"url": "https://h/x"},
        None,
    )

    payload = json.loads(captured["content"])
    assert payload["incident"]["network_verdict_note"] is not None
    assert _EN_ASN_FRAGMENT in payload["incident"]["network_verdict_note"]
    assert payload["incident"]["network_verdict"] == "network_partition_asn"


@pytest.mark.asyncio
async def test_webhook_silent_for_service_down(monkeypatch) -> None:
    captured = _patch_http(monkeypatch)
    await WebhookChannel().send(
        _incident("service_down"),
        SimpleNamespace(webhook_template=None),
        "incident_opened",
        CTX,
        {"url": "https://h/x"},
        None,
    )

    payload = json.loads(captured["content"])
    assert payload["incident"]["network_verdict_note"] is None


@pytest.mark.asyncio
async def test_webhook_template_substitutes_verdict_note(monkeypatch) -> None:
    captured = _patch_http(monkeypatch)
    await WebhookChannel().send(
        _incident("network_partition_geo"),
        SimpleNamespace(webhook_template="verdict=$network_verdict_note"),
        "incident_opened",
        CTX,
        {"url": "https://h/x"},
        None,
    )
    rendered = captured["content"].decode()
    assert _EN_GEO_FRAGMENT in rendered


# ── Email — pure function, no I/O ─────────────────────────────────────────────


def test_email_body_mentions_network_verdict() -> None:
    body = _build_email_body(
        _incident("network_partition_asn"), "incident_opened", "korben.info", "http", CTX
    )
    assert _FR_ASN_FRAGMENT in body


@pytest.mark.parametrize("verdict", _NON_PARTITIONS)
def test_email_body_silent_for_non_partitions(verdict) -> None:
    body = _build_email_body(_incident(verdict), "incident_opened", "korben.info", "http", CTX)
    assert "Réseau" not in body
