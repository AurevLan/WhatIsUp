"""Active sessions — list with metadata, revoke one, revoke all."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

TEST_PASSWORD = "TestPass1!"


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _login(client: AsyncClient, email: str, ua: str = "pytest-agent") -> dict:
    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": email, "password": TEST_PASSWORD},
        headers={"User-Agent": ua},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_sessions_listed_with_metadata(client: AsyncClient, regular_user) -> None:
    t1 = await _login(client, regular_user.email, ua="Device-A")
    t2 = await _login(client, regular_user.email, ua="Device-B")

    listed = await client.post(
        "/api/v1/auth/sessions/list",
        json={"refresh_token": t2["refresh_token"]},
        headers=_auth(t2["access_token"]),
    )
    assert listed.status_code == 200, listed.text
    sessions = listed.json()
    assert len(sessions) == 2
    uas = {s["ua"] for s in sessions}
    assert {"Device-A", "Device-B"} <= uas
    current = [s for s in sessions if s["current"]]
    assert len(current) == 1
    assert current[0]["ua"] == "Device-B"
    assert current[0]["created_at"]
    assert t1["access_token"]  # both logins valid


@pytest.mark.asyncio
async def test_revoke_session_kills_refresh(client: AsyncClient, regular_user) -> None:
    t1 = await _login(client, regular_user.email, ua="Victim")
    t2 = await _login(client, regular_user.email, ua="Mine")

    listed = await client.post(
        "/api/v1/auth/sessions/list",
        json={"refresh_token": t2["refresh_token"]},
        headers=_auth(t2["access_token"]),
    )
    victim = next(s for s in listed.json() if s["ua"] == "Victim")

    revoke = await client.delete(
        f"/api/v1/auth/sessions/{victim['id']}", headers=_auth(t2["access_token"])
    )
    assert revoke.status_code == 204

    # The revoked session's refresh token no longer works
    refresh = await client.post("/api/v1/auth/refresh", json={"refresh_token": t1["refresh_token"]})
    assert refresh.status_code == 401

    # Mine still works
    mine = await client.post("/api/v1/auth/refresh", json={"refresh_token": t2["refresh_token"]})
    assert mine.status_code == 200


@pytest.mark.asyncio
async def test_revoke_all_keeps_current(client: AsyncClient, regular_user) -> None:
    t1 = await _login(client, regular_user.email, ua="Old-1")
    t2 = await _login(client, regular_user.email, ua="Old-2")
    t3 = await _login(client, regular_user.email, ua="Current")

    resp = await client.post(
        "/api/v1/auth/sessions/revoke-all",
        json={"refresh_token": t3["refresh_token"]},
        headers=_auth(t3["access_token"]),
    )
    assert resp.status_code == 204

    for dead in (t1, t2):
        r = await client.post("/api/v1/auth/refresh", json={"refresh_token": dead["refresh_token"]})
        assert r.status_code == 401
    alive = await client.post("/api/v1/auth/refresh", json={"refresh_token": t3["refresh_token"]})
    assert alive.status_code == 200


@pytest.mark.asyncio
async def test_revoke_invalid_session_id(client: AsyncClient, user_token: str) -> None:
    resp = await client.delete("/api/v1/auth/sessions/not-a-hash", headers=_auth(user_token))
    assert resp.status_code == 400
    resp = await client.delete("/api/v1/auth/sessions/" + "0" * 32, headers=_auth(user_token))
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_session_survives_rotation_with_created_at(client: AsyncClient, regular_user) -> None:
    """Token rotation keeps the session's original created_at."""
    t = await _login(client, regular_user.email, ua="Rotator")
    listed1 = await client.post(
        "/api/v1/auth/sessions/list",
        json={"refresh_token": t["refresh_token"]},
        headers=_auth(t["access_token"]),
    )
    created_before = next(s for s in listed1.json() if s["ua"] == "Rotator")["created_at"]

    rotated = await client.post("/api/v1/auth/refresh", json={"refresh_token": t["refresh_token"]})
    assert rotated.status_code == 200
    new = rotated.json()

    listed2 = await client.post(
        "/api/v1/auth/sessions/list",
        json={"refresh_token": new["refresh_token"]},
        headers=_auth(new["access_token"]),
    )
    rotator = next(s for s in listed2.json() if s["ua"] == "Rotator")
    assert rotator["current"] is True
    assert rotator["created_at"] == created_before
