"""Coverage for SLA report generation + delivery (services/reports.py)."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import whatisup.core.database as db_mod
from whatisup.models.monitor import Monitor, MonitorGroup
from whatisup.models.probe import Probe
from whatisup.models.result import CheckResult, CheckStatus
from whatisup.models.user import User
from whatisup.services.reports import (
    check_and_send_reports,
    generate_group_report,
    send_report_email,
)


class _Ctx:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def __aenter__(self) -> AsyncSession:
        return self._session

    async def __aexit__(self, *_a) -> None:  # noqa: D401
        return None


# ── generate_group_report ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_generate_group_report_renders_rows_for_each_monitor(
    service_db: AsyncSession, test_user: User, test_probe: Probe
) -> None:
    group = MonitorGroup(name="Prod", owner_id=test_user.id, report_schedule="weekly")
    service_db.add(group)
    await service_db.flush()
    monitor = Monitor(name="api", url="http://api", owner_id=test_user.id, group_id=group.id)
    service_db.add(monitor)
    await service_db.flush()
    # 1 successful check so compute_uptime returns 100.0
    service_db.add(
        CheckResult(
            monitor_id=monitor.id,
            probe_id=test_probe.id,
            status=CheckStatus.up,
            response_time_ms=120,
            checked_at=datetime.now(UTC),
        )
    )
    await service_db.flush()

    html = await generate_group_report(service_db, group)
    assert "Weekly SLA Report" in html
    assert "Prod" in html
    assert "api" in html
    assert "100.00%" in html


@pytest.mark.asyncio
async def test_generate_group_report_monthly_label(
    service_db: AsyncSession, test_user: User
) -> None:
    group = MonitorGroup(name="Infra", owner_id=test_user.id, report_schedule="monthly")
    service_db.add(group)
    await service_db.flush()
    html = await generate_group_report(service_db, group)
    assert "Monthly SLA Report" in html


# ── send_report_email ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_report_email_skips_when_no_smtp(monkeypatch) -> None:
    """No SMTP config → silently no-op (returns None)."""
    fake = SimpleNamespace(
        smtp_host="", smtp_from="x", smtp_port=25, smtp_tls=False, smtp_user="", smtp_password=""
    )
    monkeypatch.setattr("whatisup.services.reports.get_settings", lambda: fake)
    await send_report_email(["who@example.com"], "subject", "<html/>")


@pytest.mark.asyncio
async def test_send_report_email_calls_aiosmtplib(monkeypatch) -> None:
    fake = SimpleNamespace(
        smtp_host="smtp.example",
        smtp_from="from@x",
        smtp_port=587,
        smtp_tls=True,
        smtp_user="u",
        smtp_password="p",
    )
    monkeypatch.setattr("whatisup.services.reports.get_settings", lambda: fake)
    sent = []

    async def _send(msg, **kw):
        sent.append({"to": msg["To"], "subject": msg["Subject"], "kw": kw})

    monkeypatch.setattr("aiosmtplib.send", _send)
    await send_report_email(["a@x.com", "b@x.com"], "Report", "<html/>")
    assert len(sent) == 2
    assert sent[0]["to"] == "a@x.com"
    assert sent[0]["subject"] == "Report"
    assert sent[0]["kw"]["hostname"] == "smtp.example"
    assert sent[0]["kw"]["start_tls"] is True


@pytest.mark.asyncio
async def test_send_report_email_swallows_smtp_failure(monkeypatch) -> None:
    """A failure on one recipient does not abort delivery to the rest."""
    fake = SimpleNamespace(
        smtp_host="smtp",
        smtp_from="x",
        smtp_port=25,
        smtp_tls=False,
        smtp_user="",
        smtp_password="",
    )
    monkeypatch.setattr("whatisup.services.reports.get_settings", lambda: fake)
    seen = []

    async def _send(msg, **kw):
        seen.append(msg["To"])
        if msg["To"] == "bad@x.com":
            raise RuntimeError("SMTP boom")

    monkeypatch.setattr("aiosmtplib.send", _send)
    await send_report_email(["bad@x.com", "good@x.com"], "subj", "body")
    assert seen == ["bad@x.com", "good@x.com"]


# ── check_and_send_reports ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_check_and_send_reports_skips_outside_8am(monkeypatch) -> None:
    """Outside 08:00 UTC the scheduler shouldn't touch the DB at all."""

    class _UTC(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 5, 14, 14, 0, tzinfo=UTC)

    monkeypatch.setattr("whatisup.services.reports.datetime", _UTC)
    await check_and_send_reports()  # Must not raise even with no DB patched


@pytest.mark.asyncio
async def test_check_and_send_reports_sends_weekly_on_monday(
    service_db: AsyncSession, test_user: User, test_probe: Probe, monkeypatch
) -> None:
    """At 08:00 UTC on Monday, a weekly group with emails triggers an SMTP send."""
    group = MonitorGroup(
        name="Weekly group",
        owner_id=test_user.id,
        report_schedule="weekly",
        report_emails=["sla@example.com"],
    )
    monitor = Monitor(name="m", url="http://m", owner_id=test_user.id)
    service_db.add_all([group, monitor])
    await service_db.flush()
    monitor.group_id = group.id
    await service_db.flush()

    class _Mon(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 5, 18, 8, 0, tzinfo=UTC)  # Monday 08:00

    monkeypatch.setattr("whatisup.services.reports.datetime", _Mon)
    monkeypatch.setattr(db_mod, "_async_session_factory", lambda: _Ctx(service_db))

    sent: list[str] = []

    async def _fake_email(emails, subject, html):
        sent.extend(emails)

    monkeypatch.setattr("whatisup.services.reports.send_report_email", _fake_email)
    await check_and_send_reports()
    assert sent == ["sla@example.com"]


@pytest.mark.asyncio
async def test_check_and_send_reports_skips_group_without_emails(
    service_db: AsyncSession, test_user: User, monkeypatch
) -> None:
    group = MonitorGroup(
        name="No emails", owner_id=test_user.id, report_schedule="weekly", report_emails=[]
    )
    service_db.add(group)
    await service_db.flush()

    class _Mon(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 5, 18, 8, 0, tzinfo=UTC)

    monkeypatch.setattr("whatisup.services.reports.datetime", _Mon)
    monkeypatch.setattr(db_mod, "_async_session_factory", lambda: _Ctx(service_db))

    spy = AsyncMock()
    monkeypatch.setattr("whatisup.services.reports.send_report_email", spy)
    await check_and_send_reports()
    spy.assert_not_called()
