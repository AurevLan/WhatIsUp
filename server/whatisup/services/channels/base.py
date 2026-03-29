"""Base class for alert channel plugins."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseAlertChannel(ABC):
    """Abstract base class for all alert channel plugins.

    Subclasses must define ``name`` and implement ``send()`` and ``test()``.
    """

    name: str = ""

    @abstractmethod
    async def test(self, config: dict[str, Any], settings: Any) -> tuple[bool, str]:
        """Send a test notification. Returns (success, detail_message)."""
        ...

    @abstractmethod
    async def send(
        self,
        incident: Any,
        channel: Any,
        event_type: str,
        ctx: dict[str, Any],
        config: dict[str, Any],
        settings: Any,
    ) -> str | None:
        """Send an alert. Returns optional response body string."""
        ...
