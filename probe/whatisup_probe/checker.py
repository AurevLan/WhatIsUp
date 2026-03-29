"""Backward-compatibility shim — all logic moved to whatisup_probe.checkers package."""

from whatisup_probe.checkers import CheckResult, perform_check  # noqa: F401
from whatisup_probe.checkers._shared import PlaywrightPool, kill_stale_chromium  # noqa: F401
