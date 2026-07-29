"""S4 — injections de contenu dans les sorties générées (audit F7, F17).

Trois surfaces distinctes, un même défaut : une valeur choisie par un
utilisateur est recopiée telle quelle dans un format structuré (en-tête SMTP,
document HTML) qui lui donne un sens qu'elle ne devrait pas avoir.

- F7  : `report_emails` finit dans l'en-tête `To` du rapport SLA. Un CR/LF
        encapsulé injecte des en-têtes arbitraires (`Bcc:`) dans un mail émis
        depuis l'identité SMTP alignée SPF/DKIM du serveur.
- F17 : le nom d'un monitor est interpolé dans le corps HTML des alertes, lues
        par des tiers qui ne l'ont pas choisi.

Le test du générateur Playwright de l'extension (F12) vit côté frontend, dans
`frontend/tests/extensionPlaywrightExport.test.js`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.models.incident import IncidentScope
from whatisup.models.monitor import Monitor, MonitorGroup
from whatisup.models.probe import Probe
from whatisup.models.result import CheckResult, CheckStatus
from whatisup.models.user import User
from whatisup.services.channels.email import _build_email_body
from whatisup.services.reports import generate_group_report, send_report_email

_INJECTED = "victim@corp.com\r\nBcc: attacker@evil.com"


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _smtp_settings() -> SimpleNamespace:
    return SimpleNamespace(
        smtp_host="smtp.example",
        smtp_from="from@example.com",
        smtp_port=587,
        smtp_tls=True,
        smtp_user="",
        smtp_password="",
    )


# ── F7 — validation au bord ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_group_rejects_crlf_in_report_emails(
    client: AsyncClient, user_token: str
) -> None:
    resp = await client.post(
        "/api/v1/groups/",
        json={"name": "Injected", "report_schedule": "weekly", "report_emails": [_INJECTED]},
        headers=_auth(user_token),
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_update_group_rejects_crlf_in_report_emails(
    client: AsyncClient, user_token: str
) -> None:
    created = await client.post(
        "/api/v1/groups/", json={"name": "Legit group"}, headers=_auth(user_token)
    )
    gid = created.json()["id"]
    resp = await client.patch(
        f"/api/v1/groups/{gid}",
        json={"report_emails": [_INJECTED]},
        headers=_auth(user_token),
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_group_rejects_malformed_and_oversized_recipient_lists(
    client: AsyncClient, user_token: str
) -> None:
    for payload in (
        {"name": "No at sign", "report_emails": ["not-an-email"]},
        {"name": "Too many", "report_emails": [f"u{i}@x.com" for i in range(21)]},
    ):
        resp = await client.post("/api/v1/groups/", json=payload, headers=_auth(user_token))
        assert resp.status_code == 422, payload


@pytest.mark.asyncio
async def test_valid_report_emails_still_accepted(client: AsyncClient, user_token: str) -> None:
    """Le filtre ne doit pas casser l'usage normal, création comme mise à jour.

    Le POST est vérifié pour son code de retour seulement : `create_group`
    ignore `report_schedule`/`report_emails` (seul le PATCH les persiste) —
    comportement antérieur, hors périmètre de ce lot.
    """
    created = await client.post(
        "/api/v1/groups/",
        json={
            "name": "Valid recipients",
            "report_schedule": "weekly",
            "report_emails": ["sla@example.com", "ops@example.co.uk"],
        },
        headers=_auth(user_token),
    )
    assert created.status_code in (200, 201)

    resp = await client.patch(
        f"/api/v1/groups/{created.json()['id']}",
        json={"report_emails": ["sla@example.com", "ops@example.co.uk"]},
        headers=_auth(user_token),
    )
    assert resp.status_code == 200
    assert resp.json()["report_emails"] == ["sla@example.com", "ops@example.co.uk"]


# ── F7 — garde-fou au point d'usage ───────────────────────────────────────────
#
# L'import IaC (`PUT /config/`) écrit `report_emails` depuis un `dict` brut sans
# passer par les schémas, et les lignes écrites avant ce correctif sont toujours
# en base : le mailer doit se défendre seul.


@pytest.mark.asyncio
async def test_send_report_email_drops_injected_recipient(monkeypatch) -> None:
    monkeypatch.setattr("whatisup.services.reports.get_settings", _smtp_settings)
    sent: list[str] = []

    async def _send(msg, **_kw):
        sent.append(msg["To"])

    monkeypatch.setattr("aiosmtplib.send", _send)
    await send_report_email([_INJECTED, "ok@example.com"], "Report", "<html/>")

    assert sent == ["ok@example.com"]


@pytest.mark.asyncio
async def test_sent_report_carries_no_injected_header(monkeypatch) -> None:
    """Sérialisation complète : le message émis ne contient aucun `Bcc`."""
    monkeypatch.setattr("whatisup.services.reports.get_settings", _smtp_settings)
    raw: list[bytes] = []

    async def _send(msg, **_kw):
        raw.append(msg.as_bytes())

    monkeypatch.setattr("aiosmtplib.send", _send)
    await send_report_email(["ok@example.com"], "Report", "<html/>")

    assert raw and b"Bcc" not in raw[0]
    assert b"attacker@evil.com" not in raw[0]


@pytest.mark.asyncio
async def test_send_report_email_flattens_newlines_in_subject(monkeypatch) -> None:
    """Le sujet porte le nom du groupe : un CR/LF ne doit ni injecter, ni bloquer l'envoi."""
    monkeypatch.setattr("whatisup.services.reports.get_settings", _smtp_settings)
    sent: list[tuple[str, bytes]] = []

    async def _send(msg, **_kw):
        sent.append((msg["Subject"], msg.as_bytes()))

    monkeypatch.setattr("aiosmtplib.send", _send)
    await send_report_email(
        ["ok@example.com"], "SLA Report — Prod\r\nBcc: attacker@evil.com", "<html/>"
    )

    assert len(sent) == 1
    subject, payload = sent[0]
    assert "\n" not in subject and "\r" not in subject
    # La charge reste du texte *dans* le sujet, sur une seule ligne : aucune
    # ligne du message sérialisé n'ouvre un en-tête `Bcc`.
    assert not any(line.startswith(b"Bcc") for line in payload.splitlines())


# ── F17 — échappement HTML ────────────────────────────────────────────────────


@pytest.fixture
def fake_incident() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        monitor_id=uuid.uuid4(),
        started_at=datetime(2026, 7, 28, 12, 0, tzinfo=UTC),
        resolved_at=None,
        duration_seconds=None,
        affected_probe_ids=[],
        scope=IncidentScope.global_,
    )


def test_alert_email_body_escapes_monitor_name(fake_incident: SimpleNamespace) -> None:
    hostile = '<a href="https://evil.example/reset">Confirm your account</a>'
    body = _build_email_body(
        fake_incident,
        "incident_opened",
        hostile,
        "http",
        {"monitor_name": hostile, "check_type": "http", "probe_names": {}},
    )

    assert hostile not in body
    assert "&lt;a href=" in body


def test_alert_email_body_escapes_scope_and_check_type(fake_incident: SimpleNamespace) -> None:
    """La portée est construite depuis des noms de sondes, eux aussi libres."""
    fake_incident.scope = IncidentScope.geographic
    probe_id = uuid.uuid4()
    fake_incident.affected_probe_ids = [probe_id]
    body = _build_email_body(
        fake_incident,
        "incident_opened",
        "api",
        "<img src=x onerror=alert(1)>",
        {"probe_names": {probe_id: "<script>alert(1)</script>"}},
    )

    assert "<script>" not in body
    assert "<img src=x" not in body
    assert "&lt;script&gt;" in body


@pytest.mark.asyncio
async def test_sla_report_escapes_group_and_monitor_names(
    service_db: AsyncSession, test_user: User, test_probe: Probe
) -> None:
    """Même défaut que F17, dans le rapport SLA — non signalé par l'audit."""
    group = MonitorGroup(
        name="<script>alert('group')</script>",
        owner_id=test_user.id,
        report_schedule="weekly",
    )
    service_db.add(group)
    await service_db.flush()
    monitor = Monitor(
        name="<img src=x onerror=alert(1)>",
        url="http://api",
        owner_id=test_user.id,
        group_id=group.id,
    )
    service_db.add(monitor)
    await service_db.flush()
    service_db.add(
        CheckResult(
            monitor_id=monitor.id,
            probe_id=test_probe.id,
            status=CheckStatus.up,
            response_time_ms=100,
            checked_at=datetime.now(UTC),
        )
    )
    await service_db.flush()

    html = await generate_group_report(service_db, group)

    assert "<script>alert('group')</script>" not in html
    assert "<img src=x onerror=alert(1)>" not in html
    assert "&lt;script&gt;" in html
    assert "&lt;img src=x" in html
