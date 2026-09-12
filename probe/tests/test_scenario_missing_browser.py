"""Plan cap v2, 6b — the default probe image ships without Chromium.

A `scenario` monitor assigned to a browserless probe must fail with a clear,
actionable message, never a raw Playwright stack trace ("Executable doesn't
exist at /ms-playwright/...\\nPlease run the following command..."). This is
also the exact condition our own CI runs under: `pip install -e ".[dev]"`
never runs `playwright install`, so there is no Chromium binary here either —
these tests exercise the real code path, not a mock.
"""

from __future__ import annotations

from whatisup_probe.checkers.scenario import (
    _MISSING_BROWSER_MESSAGE,
    ScenarioChecker,
    _is_missing_browser_error,
)


def test_is_missing_browser_error_detects_playwright_marker() -> None:
    exc = RuntimeError(
        "Executable doesn't exist at /ms-playwright/chromium-1234/chrome-headless-shell\n"
        "Please run the following command to download new browsers:\n\n    playwright install"
    )
    assert _is_missing_browser_error(exc) is True


def test_is_missing_browser_error_ignores_unrelated_errors() -> None:
    assert _is_missing_browser_error(TimeoutError("Timeout 30000ms exceeded")) is False


async def test_scenario_check_without_chromium_binary_fails_cleanly() -> None:
    """No browser_pool, no Chromium binary installed (true of this CI image too)."""
    checker = ScenarioChecker()
    config = {
        "steps": [{"type": "navigate", "params": {"url": "https://example.com"}}],
        "variables": [],
        "timeout_seconds": 5,
    }

    result = await checker.check("mon-1", config, browser_pool=None)

    assert result.status == "error"
    assert result.error_message == _MISSING_BROWSER_MESSAGE
    assert "browser" in _MISSING_BROWSER_MESSAGE.lower() or "navigateur" in _MISSING_BROWSER_MESSAGE
    assert "-browser" in _MISSING_BROWSER_MESSAGE
    # Never the raw Playwright trace.
    assert "Executable doesn't exist" not in result.error_message
    assert "Traceback" not in result.error_message


async def test_browser_pool_start_without_chromium_does_not_raise() -> None:
    """La sonde sans navigateur doit **démarrer**, pas seulement échouer proprement
    sur un scénario.

    Régression v2.0.0 : `PlaywrightPool.start()` signalait l'absence de binaire
    avec `logger.warning("...", hint=...)` alors que `_shared.py` utilisait le
    logger de la bibliothèque standard, qui n'accepte pas de mot-clé arbitraire.
    Le `TypeError` remontait jusqu'à `scheduler.start()` et **toute sonde sans
    navigateur plantait en boucle au démarrage** — c'est-à-dire l'image par
    défaut publiée en v2.0.0.

    Les tests existants couvraient `ScenarioChecker.check()`, jamais ce
    chemin-là : un scénario qui échoue proprement ne prouve rien si la sonde
    n'arrive jamais à démarrer.
    """
    from whatisup_probe.checkers._shared import PlaywrightPool

    pool = PlaywrightPool()

    await pool.start()  # ne doit rien lever

    assert pool._browser is None
