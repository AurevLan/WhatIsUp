"""Validation tests for T2-05 ssl_pin_sha256 + ssl_min_chain_days schema fields."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from whatisup.schemas.monitor import MonitorCreate

_BASE = {
    "name": "test",
    "url": "https://example.com",
    "check_type": "http",
    "interval_seconds": 60,
    "timeout_seconds": 10,
}


def test_pin_sha256_accepts_valid_hex() -> None:
    payload = {**_BASE, "ssl_pin_sha256": "a" * 64}
    m = MonitorCreate.model_validate(payload)
    assert m.ssl_pin_sha256 == "a" * 64


def test_pin_sha256_rejects_uppercase() -> None:
    with pytest.raises(ValidationError):
        MonitorCreate.model_validate({**_BASE, "ssl_pin_sha256": "A" * 64})


def test_pin_sha256_rejects_too_short() -> None:
    with pytest.raises(ValidationError):
        MonitorCreate.model_validate({**_BASE, "ssl_pin_sha256": "a" * 32})


def test_pin_sha256_rejects_colons() -> None:
    with pytest.raises(ValidationError):
        MonitorCreate.model_validate({**_BASE, "ssl_pin_sha256": "a:" * 32})


def test_pin_sha256_optional_none() -> None:
    m = MonitorCreate.model_validate(_BASE)
    assert m.ssl_pin_sha256 is None
    assert m.ssl_min_chain_days is None


def test_min_chain_days_in_range() -> None:
    m = MonitorCreate.model_validate({**_BASE, "ssl_min_chain_days": 14})
    assert m.ssl_min_chain_days == 14


def test_min_chain_days_rejects_zero() -> None:
    with pytest.raises(ValidationError):
        MonitorCreate.model_validate({**_BASE, "ssl_min_chain_days": 0})


def test_min_chain_days_rejects_above_year() -> None:
    with pytest.raises(ValidationError):
        MonitorCreate.model_validate({**_BASE, "ssl_min_chain_days": 366})
