"""2FA TOTP — enrollment, login challenge, verify, recovery codes, disable."""

from __future__ import annotations

import time

import pyotp
import pytest
from httpx import AsyncClient

TEST_PASSWORD = "TestPass1!"


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _enroll(client: AsyncClient, token: str) -> tuple[str, list[str]]:
    """Run setup + enable; return (secret, recovery_codes)."""
    setup = await client.post("/api/v1/auth/totp/setup", headers=_auth(token))
    assert setup.status_code == 200, setup.text
    secret = setup.json()["secret"]
    assert "otpauth://" in setup.json()["otpauth_url"]

    code = pyotp.TOTP(secret).now()
    enable = await client.post(
        "/api/v1/auth/totp/enable", json={"code": code}, headers=_auth(token)
    )
    assert enable.status_code == 200, enable.text
    codes = enable.json()["recovery_codes"]
    assert len(codes) == 8
    return secret, codes


@pytest.mark.asyncio
async def test_full_totp_flow(client: AsyncClient, regular_user, user_token: str) -> None:
    secret, _codes = await _enroll(client, user_token)

    # Login now returns an MFA challenge instead of tokens
    login = await client.post(
        "/api/v1/auth/login",
        data={"username": regular_user.email, "password": TEST_PASSWORD},
    )
    assert login.status_code == 200
    body = login.json()
    assert body["mfa_required"] is True
    assert body["mfa_token"]
    assert body["access_token"] is None

    # Exchange the challenge + a fresh code (next time step — the enroll code
    # is already consumed by the replay guard; valid_window=1 accepts ±1 step)
    code = pyotp.TOTP(secret).at(time.time() + 30)
    verify = await client.post(
        "/api/v1/auth/totp/verify",
        json={"mfa_token": body["mfa_token"], "code": code},
    )
    assert verify.status_code == 200, verify.text
    tokens = verify.json()
    assert tokens["access_token"]
    assert tokens["refresh_token"]

    # The access token works
    me = await client.get("/api/v1/auth/me", headers=_auth(tokens["access_token"]))
    assert me.status_code == 200
    assert me.json()["totp_enabled"] is True


@pytest.mark.asyncio
async def test_totp_code_replay_rejected(
    client: AsyncClient, regular_user, user_token: str
) -> None:
    secret, _ = await _enroll(client, user_token)
    login = await client.post(
        "/api/v1/auth/login",
        data={"username": regular_user.email, "password": TEST_PASSWORD},
    )
    mfa_token = login.json()["mfa_token"]

    code = pyotp.TOTP(secret).at(time.time() + 30)
    first = await client.post(
        "/api/v1/auth/totp/verify", json={"mfa_token": mfa_token, "code": code}
    )
    assert first.status_code == 200

    # Same code again within its window → rejected (replay guard)
    login2 = await client.post(
        "/api/v1/auth/login",
        data={"username": regular_user.email, "password": TEST_PASSWORD},
    )
    second = await client.post(
        "/api/v1/auth/totp/verify",
        json={"mfa_token": login2.json()["mfa_token"], "code": code},
    )
    assert second.status_code == 401


@pytest.mark.asyncio
async def test_recovery_code_single_use(client: AsyncClient, regular_user, user_token: str) -> None:
    _secret, codes = await _enroll(client, user_token)
    recovery = codes[0]

    login = await client.post(
        "/api/v1/auth/login",
        data={"username": regular_user.email, "password": TEST_PASSWORD},
    )
    ok = await client.post(
        "/api/v1/auth/totp/verify",
        json={"mfa_token": login.json()["mfa_token"], "code": recovery},
    )
    assert ok.status_code == 200

    # Consumed: the same recovery code is rejected next time
    login2 = await client.post(
        "/api/v1/auth/login",
        data={"username": regular_user.email, "password": TEST_PASSWORD},
    )
    again = await client.post(
        "/api/v1/auth/totp/verify",
        json={"mfa_token": login2.json()["mfa_token"], "code": recovery},
    )
    assert again.status_code == 401


@pytest.mark.asyncio
async def test_enable_with_wrong_code_fails(client: AsyncClient, user_token: str) -> None:
    setup = await client.post("/api/v1/auth/totp/setup", headers=_auth(user_token))
    assert setup.status_code == 200
    enable = await client.post(
        "/api/v1/auth/totp/enable", json={"code": "000000"}, headers=_auth(user_token)
    )
    assert enable.status_code == 400


@pytest.mark.asyncio
async def test_verify_rejects_access_token_as_mfa_token(
    client: AsyncClient, regular_user, user_token: str
) -> None:
    """An access token must not be usable as an MFA challenge token."""
    secret, _ = await _enroll(client, user_token)
    code = pyotp.TOTP(secret).now()
    resp = await client.post(
        "/api/v1/auth/totp/verify", json={"mfa_token": user_token, "code": code}
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_disable_requires_password_and_code(
    client: AsyncClient, regular_user, user_token: str
) -> None:
    secret, _ = await _enroll(client, user_token)

    bad_pwd = await client.post(
        "/api/v1/auth/totp/disable",
        json={"password": "WrongPass1!", "code": pyotp.TOTP(secret).at(time.time() + 30)},
        headers=_auth(user_token),
    )
    assert bad_pwd.status_code == 401

    bad_code = await client.post(
        "/api/v1/auth/totp/disable",
        json={"password": TEST_PASSWORD, "code": "000000"},
        headers=_auth(user_token),
    )
    assert bad_code.status_code == 401

    ok = await client.post(
        "/api/v1/auth/totp/disable",
        json={"password": TEST_PASSWORD, "code": pyotp.TOTP(secret).at(time.time() + 30)},
        headers=_auth(user_token),
    )
    assert ok.status_code == 204

    # Login is back to direct tokens
    login = await client.post(
        "/api/v1/auth/login",
        data={"username": regular_user.email, "password": TEST_PASSWORD},
    )
    assert login.json()["mfa_required"] is False
    assert login.json()["access_token"]


@pytest.mark.asyncio
async def test_login_without_totp_unchanged(client: AsyncClient, regular_user) -> None:
    """Accounts without 2FA keep the historical login shape (tokens directly)."""
    login = await client.post(
        "/api/v1/auth/login",
        data={"username": regular_user.email, "password": TEST_PASSWORD},
    )
    assert login.status_code == 200
    body = login.json()
    assert body["access_token"] and body["refresh_token"]
    assert body["mfa_required"] is False
