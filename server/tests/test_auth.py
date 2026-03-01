"""Tests for authentication endpoints."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_register_first_user_becomes_superadmin(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/auth/register", json={
        "email": "admin@example.com",
        "username": "admin",
        "password": "SecurePass1",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["is_superadmin"] is True
    assert data["username"] == "admin"


@pytest.mark.asyncio
async def test_register_second_user_is_not_superadmin(client: AsyncClient) -> None:
    await client.post("/api/v1/auth/register", json={
        "email": "admin2@example.com",
        "username": "admin2",
        "password": "SecurePass1",
    })
    resp = await client.post("/api/v1/auth/register", json={
        "email": "user@example.com",
        "username": "normaluser",
        "password": "SecurePass1",
    })
    assert resp.status_code == 201
    assert resp.json()["is_superadmin"] is False


@pytest.mark.asyncio
async def test_login_success(client: AsyncClient) -> None:
    await client.post("/api/v1/auth/register", json={
        "email": "login_test@example.com",
        "username": "logintest",
        "password": "SecurePass1",
    })
    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": "login_test@example.com", "password": "SecurePass1"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_login_wrong_password(client: AsyncClient) -> None:
    await client.post("/api/v1/auth/register", json={
        "email": "wrong@example.com",
        "username": "wrongpw",
        "password": "SecurePass1",
    })
    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": "wrong@example.com", "password": "WrongPassword9"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_register_duplicate_email(client: AsyncClient) -> None:
    await client.post("/api/v1/auth/register", json={
        "email": "dup@example.com",
        "username": "dup1",
        "password": "SecurePass1",
    })
    resp = await client.post("/api/v1/auth/register", json={
        "email": "dup@example.com",
        "username": "dup2",
        "password": "SecurePass1",
    })
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_health_endpoint(client: AsyncClient) -> None:
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
