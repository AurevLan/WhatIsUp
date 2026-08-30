"""Tests for the onboarding flow."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from whatisup.core.config import get_settings
from whatisup.schemas.user import UserOut

# ── UserOut.onboarding_completed computed field ──────────────────────────────


def test_user_out_onboarding_false_when_null() -> None:
    """onboarding_completed should be False when onboarding_completed_at is None."""
    out = UserOut(
        id="00000000-0000-0000-0000-000000000001",
        email="a@b.com",
        username="test",
        full_name=None,
        is_active=True,
        is_superadmin=False,
        can_create_monitors=False,
        onboarding_completed=False,
    )
    assert out.onboarding_completed is False


def test_user_out_onboarding_true_when_set() -> None:
    """onboarding_completed should be True when explicitly set."""
    out = UserOut(
        id="00000000-0000-0000-0000-000000000001",
        email="a@b.com",
        username="test",
        full_name=None,
        is_active=True,
        is_superadmin=False,
        can_create_monitors=False,
        onboarding_completed=True,
    )
    assert out.onboarding_completed is True


# ── GET /onboarding/status ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_onboarding_status_new_user(client: AsyncClient, user_token: str) -> None:
    """New user (no monitors, no onboarding) should show completed=False."""
    resp = await client.get(
        "/api/v1/onboarding/status",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["completed"] is False
    assert data["completed_at"] is None
    assert data["has_monitors"] is False
    assert data["has_alert_channels"] is False
    assert data["monitor_count"] == 0
    assert data["channel_count"] == 0


# ── POST /onboarding/complete ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_onboarding_complete(client: AsyncClient, user_token: str) -> None:
    """Completing onboarding should set completed=True."""
    resp = await client.post(
        "/api/v1/onboarding/complete",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["completed"] is True
    assert data["completed_at"] is not None


@pytest.mark.asyncio
async def test_onboarding_complete_idempotent(client: AsyncClient, user_token: str) -> None:
    """Calling complete twice should not error."""
    await client.post(
        "/api/v1/onboarding/complete",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    resp = await client.post(
        "/api/v1/onboarding/complete",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["completed"] is True


@pytest.mark.asyncio
async def test_onboarding_status_after_complete(client: AsyncClient, user_token: str) -> None:
    """Status should reflect completed=True after complete is called."""
    await client.post(
        "/api/v1/onboarding/complete",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    resp = await client.get(
        "/api/v1/onboarding/status",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["completed"] is True


# ── email_available reflects SMTP configuration (plan_cap_v2.md, étape 2) ────


@pytest.mark.asyncio
async def test_onboarding_status_email_available_when_smtp_host_set(
    client: AsyncClient, user_token: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """email_available should be True when a non-blank SMTP host is configured."""
    monkeypatch.setattr(get_settings(), "smtp_host", "smtp.example.com")
    resp = await client.get(
        "/api/v1/onboarding/status",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["email_available"] is True


@pytest.mark.asyncio
async def test_onboarding_status_email_unavailable_when_smtp_host_empty(
    client: AsyncClient, user_token: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """email_available should be False when the SMTP host is an empty string."""
    monkeypatch.setattr(get_settings(), "smtp_host", "")
    resp = await client.get(
        "/api/v1/onboarding/status",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["email_available"] is False


@pytest.mark.asyncio
async def test_onboarding_status_email_unavailable_when_smtp_host_blank(
    client: AsyncClient, user_token: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """email_available should be False for a whitespace-only SMTP host (docker-compose.yml
    style `SMTP_HOST: ${SMTP_HOST:-}` can produce blank-but-not-empty values)."""
    monkeypatch.setattr(get_settings(), "smtp_host", "   ")
    resp = await client.get(
        "/api/v1/onboarding/status",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["email_available"] is False


# ── Status reflects monitors/channels ────────────────────────────────────────


@pytest.mark.asyncio
async def test_onboarding_status_after_monitor_created(
    client: AsyncClient, admin_token: str
) -> None:
    """Creating a monitor should update has_monitors and monitor_count."""
    create_resp = await client.post(
        "/api/v1/monitors/",
        json={
            "name": "Onboard Test",
            "url": "https://example.com",
            "check_type": "http",
            "expected_status_codes": [200],
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert create_resp.status_code == 201

    resp = await client.get(
        "/api/v1/onboarding/status",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["has_monitors"] is True
    assert data["monitor_count"] >= 1
