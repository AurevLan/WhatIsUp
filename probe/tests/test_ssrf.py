"""Tests for SSRF host validation in the probe."""

import socket

import pytest

from whatisup_probe.checkers._shared import validate_host_ssrf


def test_validate_host_ssrf_blocks_localhost():
    result = validate_host_ssrf("localhost")
    assert result is not None
    assert "localhost" in result


def test_validate_host_ssrf_blocks_internal_ip():
    result = validate_host_ssrf("127.0.0.1")
    assert result is not None
    assert "127.0.0.1" in result


def test_validate_host_ssrf_blocks_metadata():
    result = validate_host_ssrf("169.254.169.254")
    assert result is not None
    assert "169.254.169.254" in result


def test_validate_host_ssrf_allows_public(monkeypatch):
    # Return a public IP so DNS resolution doesn't fail or block
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, port, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))
        ],
    )
    result = validate_host_ssrf("example.com")
    assert result is None
