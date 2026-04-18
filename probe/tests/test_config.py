"""Tests for probe config validation."""

import pytest

import whatisup_probe.config as config_module
from whatisup_probe.config import get_settings


def test_empty_api_key_raises(monkeypatch):
    monkeypatch.setenv("PROBE_API_KEY", "")
    config_module._settings = None
    with pytest.raises(Exception, match="PROBE_API_KEY"):
        get_settings()


def test_invalid_prefix_raises(monkeypatch):
    monkeypatch.setenv("PROBE_API_KEY", "bad_key")
    config_module._settings = None
    with pytest.raises(Exception, match="wiu_"):
        get_settings()


def test_valid_key_accepted(monkeypatch):
    monkeypatch.setenv("PROBE_API_KEY", "wiu_test_key")
    config_module._settings = None
    settings = get_settings()
    assert settings.probe_api_key == "wiu_test_key"
