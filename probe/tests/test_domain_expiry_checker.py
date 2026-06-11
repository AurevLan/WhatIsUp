"""Tests for the domain WHOIS expiry checker (whois module stubbed, no real network)."""

from __future__ import annotations

import sys
import time
import types
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from whatisup_probe.checkers.domain_expiry import DomainExpiryChecker


def _config(**overrides: Any) -> dict[str, Any]:
    config: dict[str, Any] = {"url": "https://example.com", "timeout_seconds": 5}
    config.update(overrides)
    return config


def _stub_whois(monkeypatch, expiration_date: Any = None, exc: Exception | None = None) -> None:
    """Inject a fake `whois` module whose whois() returns the given expiry or raises."""

    def fake_whois(host: str) -> types.SimpleNamespace:
        if exc is not None:
            raise exc
        return types.SimpleNamespace(expiration_date=expiration_date)

    monkeypatch.setitem(sys.modules, "whois", types.SimpleNamespace(whois=fake_whois))


@pytest.mark.asyncio
async def test_domain_up_far_from_expiry(monkeypatch) -> None:
    """A domain expiring well beyond the warn threshold is up."""
    expiry = datetime.now(UTC) + timedelta(days=365)
    _stub_whois(monkeypatch, expiration_date=expiry)

    result = await DomainExpiryChecker().check("dom-up", _config())

    assert result.status == "up"
    assert result.error_message is None
    assert result.ssl_expires_at == expiry
    assert result.ssl_days_remaining in (364, 365)
    assert result.response_time_ms is not None


@pytest.mark.asyncio
async def test_domain_down_within_warn_threshold(monkeypatch) -> None:
    """A domain expiring inside the warn window is reported down."""
    _stub_whois(monkeypatch, expiration_date=datetime.now(UTC) + timedelta(days=10))

    result = await DomainExpiryChecker().check("dom-warn", _config(domain_expiry_warn_days=30))

    assert result.status == "down"
    assert "threshold: 30d" in (result.error_message or "")
    assert result.ssl_days_remaining is not None
    assert 0 < result.ssl_days_remaining <= 10


@pytest.mark.asyncio
async def test_domain_down_when_expired(monkeypatch) -> None:
    _stub_whois(monkeypatch, expiration_date=datetime.now(UTC) - timedelta(days=5))

    result = await DomainExpiryChecker().check("dom-expired", _config())

    assert result.status == "down"
    assert "Domain expired" in (result.error_message or "")
    assert result.ssl_days_remaining is not None
    assert result.ssl_days_remaining < 0


@pytest.mark.asyncio
async def test_domain_expiry_list_uses_first_entry(monkeypatch) -> None:
    """Some registrars return a list of dates — the first one is used."""
    first = datetime.now(UTC) + timedelta(days=400)
    second = datetime.now(UTC) + timedelta(days=2)
    _stub_whois(monkeypatch, expiration_date=[first, second])

    result = await DomainExpiryChecker().check("dom-list", _config())

    assert result.status == "up"
    assert result.ssl_expires_at == first


@pytest.mark.asyncio
async def test_domain_naive_expiry_treated_as_utc(monkeypatch) -> None:
    """Naive WHOIS datetimes must not crash the UTC subtraction."""
    naive = datetime.now(UTC).replace(tzinfo=None) + timedelta(days=200)
    _stub_whois(monkeypatch, expiration_date=naive)

    result = await DomainExpiryChecker().check("dom-naive", _config())

    assert result.status == "up"
    assert result.ssl_expires_at == naive.replace(tzinfo=UTC)


@pytest.mark.asyncio
async def test_domain_error_when_no_expiry_found(monkeypatch) -> None:
    _stub_whois(monkeypatch, expiration_date=None)

    result = await DomainExpiryChecker().check("dom-none", _config())

    assert result.status == "error"
    assert "Could not determine domain expiry date" in (result.error_message or "")


@pytest.mark.asyncio
async def test_domain_error_on_whois_failure(monkeypatch) -> None:
    _stub_whois(monkeypatch, exc=RuntimeError("rate limited"))

    result = await DomainExpiryChecker().check("dom-fail", _config())

    assert result.status == "error"
    assert "WHOIS error: RuntimeError: rate limited" in (result.error_message or "")


@pytest.mark.asyncio
async def test_domain_whois_timeout(monkeypatch) -> None:
    """A WHOIS lookup slower than timeout_seconds yields status=timeout."""

    def slow_whois(host: str) -> types.SimpleNamespace:
        time.sleep(0.2)
        return types.SimpleNamespace(expiration_date=datetime.now(UTC) + timedelta(days=365))

    monkeypatch.setitem(sys.modules, "whois", types.SimpleNamespace(whois=slow_whois))

    result = await DomainExpiryChecker().check("dom-timeout", _config(timeout_seconds=0))

    assert result.status == "timeout"
    assert "WHOIS timeout after 0s" in (result.error_message or "")
