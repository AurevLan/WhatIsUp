"""Probe test configuration — ensure consistent env for all tests."""

import os
from unittest.mock import AsyncMock, patch

import pytest

import whatisup_probe.config as config_module

# Force localhost URL for tests (Docker image sets CENTRAL_API_URL=http://server:8000)
os.environ["CENTRAL_API_URL"] = "http://localhost:8000"


@pytest.fixture(autouse=True)
def _reset_settings():
    """Reset cached settings singleton after each test."""
    yield
    config_module._settings = None


@pytest.fixture(autouse=True)
def _bypass_ssrf_check():
    """Disable SSRF DNS validation in tests (fake hostnames won't resolve)."""
    with patch(
        "whatisup_probe.checkers._shared.validate_url_ssrf",
        new_callable=AsyncMock,
        return_value=None,
    ) as mock_ssrf:
        # Also patch the reference imported into http.py
        with patch(
            "whatisup_probe.checkers.http.validate_url_ssrf",
            mock_ssrf,
        ):
            yield


@pytest.fixture(autouse=True)
def _stub_public_ip_resolver(request):
    """V2-02-07: short-circuit the outbound IP resolver so respx tests don't see
    surprise calls to api.ipify.org. The dedicated test_public_ip module skips
    this fixture so it can exercise the real resolver path."""
    if "test_public_ip" in request.node.nodeid:
        yield
        return
    with patch(
        "whatisup_probe.public_ip.resolve_public_ip",
        new_callable=AsyncMock,
        return_value=None,
    ):
        yield
