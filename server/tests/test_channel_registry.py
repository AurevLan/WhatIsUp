"""Tests for the alert channel plugin registry."""

from __future__ import annotations

from whatisup.services.channels import CHANNEL_REGISTRY
from whatisup.services.channels.base import BaseAlertChannel


def test_registry_contains_all_builtin_channels() -> None:
    expected = {"email", "webhook", "telegram", "slack", "pagerduty", "opsgenie"}
    assert expected == set(CHANNEL_REGISTRY.keys())


def test_all_channels_inherit_from_base() -> None:
    for name, channel in CHANNEL_REGISTRY.items():
        assert isinstance(channel, BaseAlertChannel), (
            f"{name} does not inherit from BaseAlertChannel"
        )


def test_each_channel_has_name() -> None:
    for name, channel in CHANNEL_REGISTRY.items():
        assert channel.name == name, f"Channel registered as {name!r} has name={channel.name!r}"


def test_each_channel_has_test_and_send_methods() -> None:
    for name, channel in CHANNEL_REGISTRY.items():
        assert callable(getattr(channel, "test", None)), f"{name} missing test()"
        assert callable(getattr(channel, "send", None)), f"{name} missing send()"
