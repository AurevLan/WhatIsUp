"""Probe test configuration — ensure consistent env for all tests."""

import os
from unittest.mock import AsyncMock, patch

import pytest

# Force localhost URL for tests (Docker image sets CENTRAL_API_URL=http://server:8000)
os.environ["CENTRAL_API_URL"] = "http://localhost:8000"


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
