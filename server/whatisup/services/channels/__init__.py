"""Alert channel plugin system — registry and dispatch.

Usage::

    from whatisup.services.channels import CHANNEL_REGISTRY, test_channel, dispatch_channel

All built-in channels are auto-registered on import.
"""

from __future__ import annotations

import logging

from .base import BaseAlertChannel

logger = logging.getLogger(__name__)

# ── Registry ──────────────────────────────────────────────────────────────────

CHANNEL_REGISTRY: dict[str, BaseAlertChannel] = {}


def register(channel: BaseAlertChannel) -> BaseAlertChannel:
    """Register a channel instance by its name."""
    CHANNEL_REGISTRY[channel.name] = channel
    return channel


def _load_builtins() -> None:
    """Import all built-in channel modules and call their setup(register)."""
    from . import email, fcm, opsgenie, pagerduty, signal, slack, telegram, webhook

    for module in (email, webhook, telegram, slack, pagerduty, opsgenie, signal, fcm):
        module.setup(register)


_load_builtins()


__all__ = [
    "BaseAlertChannel",
    "CHANNEL_REGISTRY",
    "register",
]
