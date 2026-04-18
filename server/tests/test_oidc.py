"""Tests for OIDC auth endpoints when OIDC is not configured."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


# ── oidc/config ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_oidc_config_when_disabled(client: AsyncClient) -> None:
    """GET /oidc/config returns enabled=false when no OIDC env vars are set."""
    resp = await client.get("/api/v1/auth/oidc/config")
    assert resp.status_code == 200
    data = resp.json()
    assert "enabled" in data
    assert data["enabled"] is False


# ── oidc/login ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_oidc_login_when_disabled(client: AsyncClient) -> None:
    """GET /oidc/login returns 404 when OIDC is not enabled."""
    resp = await client.get("/api/v1/auth/oidc/login", follow_redirects=False)
    assert resp.status_code == 404
    assert "not enabled" in resp.json()["detail"].lower()


# ── oidc/callback ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_oidc_callback_invalid_state_when_disabled(client: AsyncClient) -> None:
    """GET /oidc/callback returns 404 when OIDC is not enabled (checked before state)."""
    resp = await client.get(
        "/api/v1/auth/oidc/callback",
        params={"code": "fake_code", "state": "bad_state"},
        follow_redirects=False,
    )
    # OIDC is disabled → endpoint raises 404 before even validating state
    assert resp.status_code == 404
    assert "not enabled" in resp.json()["detail"].lower()
