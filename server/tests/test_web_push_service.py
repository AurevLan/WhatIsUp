"""Coverage for the VAPID web-push dispatcher (services/web_push.py)."""

from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.models.user import User
from whatisup.services.web_push import (
    dispatch_web_push_for_incident,
    send_push_to_user,
)


@pytest.fixture(autouse=True)
def _stub_pywebpush(monkeypatch):
    """The pywebpush dependency isn't installed in CI — provide a stub."""

    class WebPushException(Exception):
        def __init__(self, status_code=410):
            super().__init__("expired")
            self.response = SimpleNamespace(status_code=status_code)

    def _ok(**_kw):
        return None

    stub = SimpleNamespace(WebPushException=WebPushException, webpush=_ok)
    monkeypatch.setitem(sys.modules, "pywebpush", stub)
    return stub


@pytest.fixture
def vapid_settings(monkeypatch):
    settings = SimpleNamespace(
        vapid_private_key="priv",
        vapid_public_key="pub",
        vapid_contact_email="ops@example.com",
    )
    monkeypatch.setattr("whatisup.services.web_push.get_settings", lambda: settings)
    return settings


@pytest.mark.asyncio
async def test_send_push_short_circuits_without_vapid_keys(
    service_db: AsyncSession, test_user: User, monkeypatch
) -> None:
    no_vapid = SimpleNamespace(
        vapid_private_key=None, vapid_public_key=None, vapid_contact_email=""
    )
    monkeypatch.setattr("whatisup.services.web_push.get_settings", lambda: no_vapid)
    # Must not raise and must not touch pywebpush.
    await send_push_to_user(service_db, test_user.id, "t", "b")


@pytest.mark.asyncio
async def test_send_push_skips_when_user_has_no_subscriptions(
    service_db: AsyncSession, test_user: User, vapid_settings
) -> None:
    await send_push_to_user(service_db, test_user.id, "title", "body")


@pytest.mark.asyncio
async def test_send_push_dispatches_to_all_subscriptions(
    service_db: AsyncSession, test_user: User, vapid_settings, monkeypatch
) -> None:
    from whatisup.models.web_push import WebPushSubscription

    for i in range(2):
        service_db.add(
            WebPushSubscription(
                user_id=test_user.id,
                endpoint=f"https://push.example/{i}",
                p256dh="p",
                auth="a",
            )
        )
    await service_db.flush()

    calls = []

    def _capture(endpoint, p256dh, auth, payload, private_key, contact):
        calls.append({"endpoint": endpoint, "payload": payload, "contact": contact})

    monkeypatch.setattr("whatisup.services.web_push._send_one", _capture)
    await send_push_to_user(service_db, test_user.id, "Alert", "Down", url="/m/1")
    assert len(calls) == 2
    assert '"title": "Alert"' in calls[0]["payload"]
    assert '"url": "/m/1"' in calls[0]["payload"]


@pytest.mark.asyncio
async def test_send_push_removes_expired_subscriptions(
    service_db: AsyncSession, test_user: User, vapid_settings, _stub_pywebpush, monkeypatch
) -> None:
    """A 410 response from a subscription queues it for deletion."""
    from whatisup.models.web_push import WebPushSubscription

    sub = WebPushSubscription(
        user_id=test_user.id,
        endpoint="https://push.example/expired",
        p256dh="p",
        auth="a",
    )
    service_db.add(sub)
    await service_db.flush()
    sub_id = sub.id

    def _raise_410(*_args, **_kw):
        raise _stub_pywebpush.WebPushException(status_code=410)

    monkeypatch.setattr("whatisup.services.web_push._send_one", _raise_410)
    await send_push_to_user(service_db, test_user.id, "Alert", "Down")

    remaining = (
        await service_db.execute(
            select(WebPushSubscription).where(WebPushSubscription.id == sub_id)
        )
    ).scalar_one_or_none()
    assert remaining is None


@pytest.mark.asyncio
async def test_send_push_other_errors_logged_but_subscription_kept(
    service_db: AsyncSession, test_user: User, vapid_settings, monkeypatch
) -> None:
    from whatisup.models.web_push import WebPushSubscription

    sub = WebPushSubscription(
        user_id=test_user.id,
        endpoint="https://push.example/transient",
        p256dh="p",
        auth="a",
    )
    service_db.add(sub)
    await service_db.flush()
    sub_id = sub.id

    def _raise_generic(*_args, **_kw):
        raise RuntimeError("transient")

    monkeypatch.setattr("whatisup.services.web_push._send_one", _raise_generic)
    await send_push_to_user(service_db, test_user.id, "x", "y")

    remaining = await service_db.get(WebPushSubscription, sub_id)
    assert remaining is not None


# ── dispatch_web_push_for_incident ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dispatch_routes_opened_event(monkeypatch) -> None:
    spy = AsyncMock()
    monkeypatch.setattr("whatisup.services.web_push.send_push_to_user", spy)
    monitor = SimpleNamespace(id="m1", name="api", owner_id="o1")
    await dispatch_web_push_for_incident(None, None, monitor, "incident_opened")
    spy.assert_awaited_once()
    args, kwargs = spy.call_args
    assert args[2].startswith("🔴")
    assert kwargs["url"] == "/monitors"


@pytest.mark.asyncio
async def test_dispatch_routes_resolved_event(monkeypatch) -> None:
    spy = AsyncMock()
    monkeypatch.setattr("whatisup.services.web_push.send_push_to_user", spy)
    monitor = SimpleNamespace(id="m1", name="api", owner_id="o1")
    await dispatch_web_push_for_incident(None, None, monitor, "incident_resolved")
    args, _ = spy.call_args
    assert args[2].startswith("✅")


@pytest.mark.asyncio
async def test_dispatch_ignores_unrelated_event(monkeypatch) -> None:
    spy = AsyncMock()
    monkeypatch.setattr("whatisup.services.web_push.send_push_to_user", spy)
    await dispatch_web_push_for_incident(None, None, SimpleNamespace(), "incident_renotify")
    spy.assert_not_called()


@pytest.mark.asyncio
async def test_dispatch_swallows_inner_failure(monkeypatch) -> None:
    async def _boom(*_a, **_k):
        raise RuntimeError("network down")

    monkeypatch.setattr("whatisup.services.web_push.send_push_to_user", _boom)
    monitor = SimpleNamespace(id="m1", name="api", owner_id="o1")
    # Must NOT raise — dispatcher logs and returns None.
    await dispatch_web_push_for_incident(None, None, monitor, "incident_opened")
