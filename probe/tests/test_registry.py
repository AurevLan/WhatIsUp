"""Tests for the checker plugin registry."""

from __future__ import annotations

import httpx
import pytest
import respx

from whatisup_probe.checkers import REGISTRY, perform_check
from whatisup_probe.checkers.base import BaseChecker

# ── Registry completeness ────────────────────────────────────────────────────


def test_registry_contains_all_builtin_types() -> None:
    expected = {
        "http",
        "keyword",
        "json_path",
        "tcp",
        "dns",
        "smtp",
        "ping",
        "domain_expiry",
        "scenario",
    }
    assert expected == set(REGISTRY.keys())


def test_all_checkers_inherit_from_base() -> None:
    for name, checker in REGISTRY.items():
        assert isinstance(checker, BaseChecker), f"{name} does not inherit from BaseChecker"


def test_http_aliases_keyword_and_json_path() -> None:
    assert REGISTRY["keyword"] is REGISTRY["http"]
    assert REGISTRY["json_path"] is REGISTRY["http"]


def test_each_checker_has_name() -> None:
    seen_names = set()
    for name, checker in REGISTRY.items():
        assert checker.name, f"Checker registered as {name!r} has no name"
        seen_names.add(checker.name)
    # At least 7 unique checkers (http shares with keyword/json_path)
    assert len(seen_names) >= 7


# ── Fallback on unknown type ─────────────────────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_unknown_check_type_falls_back_to_http() -> None:
    respx.get("https://example.com").mock(return_value=httpx.Response(200))
    result = await perform_check(
        monitor_id="fallback-test",
        url="https://example.com",
        timeout_seconds=10,
        follow_redirects=True,
        expected_status_codes=[200],
        ssl_check_enabled=False,
        check_type="nonexistent_type",
    )
    assert result.status == "up"
    assert result.http_status == 200


# ── Keyword check via registry ───────────────────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_keyword_check_passes_when_found() -> None:
    respx.get("https://example.com").mock(
        return_value=httpx.Response(200, text="OK healthy server")
    )
    result = await perform_check(
        monitor_id="keyword-test",
        url="https://example.com",
        timeout_seconds=10,
        follow_redirects=True,
        expected_status_codes=[200],
        ssl_check_enabled=False,
        check_type="keyword",
        keyword="healthy",
    )
    assert result.status == "up"


@pytest.mark.asyncio
@respx.mock
async def test_keyword_check_fails_when_not_found() -> None:
    respx.get("https://example.com").mock(return_value=httpx.Response(200, text="something else"))
    result = await perform_check(
        monitor_id="keyword-fail-test",
        url="https://example.com",
        timeout_seconds=10,
        follow_redirects=True,
        expected_status_codes=[200],
        ssl_check_enabled=False,
        check_type="keyword",
        keyword="healthy",
    )
    assert result.status == "down"
    assert "keyword" in (result.error_message or "").lower()


# ── JSON path check via registry ─────────────────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_json_path_check_passes() -> None:
    respx.get("https://api.example.com/health").mock(
        return_value=httpx.Response(200, json={"status": "ok", "version": "1.0"})
    )
    result = await perform_check(
        monitor_id="jsonpath-test",
        url="https://api.example.com/health",
        timeout_seconds=10,
        follow_redirects=True,
        expected_status_codes=[200],
        ssl_check_enabled=False,
        check_type="json_path",
        expected_json_path="$.status",
        expected_json_value="ok",
    )
    assert result.status == "up"


@pytest.mark.asyncio
@respx.mock
async def test_json_path_check_fails_on_mismatch() -> None:
    respx.get("https://api.example.com/health").mock(
        return_value=httpx.Response(200, json={"status": "error"})
    )
    result = await perform_check(
        monitor_id="jsonpath-fail",
        url="https://api.example.com/health",
        timeout_seconds=10,
        follow_redirects=True,
        expected_status_codes=[200],
        ssl_check_enabled=False,
        check_type="json_path",
        expected_json_path="$.status",
        expected_json_value="ok",
    )
    assert result.status == "down"
    assert "JSON path" in (result.error_message or "")


# ── keyword/json_path as http assertions (plan cap v2, 6f-2) ────────────────
#
# After the migration, the server never sends check_type "keyword"/"json_path"
# again — every monitor that used to carry one of those two types is now
# check_type="http" with its assertion fields untouched. Before this lot,
# HTTPChecker only evaluated expected_json_path/expected_json_value when
# check_type == "json_path" — an http monitor with expected_json_path set
# would have silently never run the assertion. These pin the fix.


@pytest.mark.asyncio
@respx.mock
async def test_keyword_assertion_evaluated_on_http_check_type() -> None:
    respx.get("https://example.com").mock(return_value=httpx.Response(200, text="something else"))
    result = await perform_check(
        monitor_id="http-with-keyword",
        url="https://example.com",
        timeout_seconds=10,
        follow_redirects=True,
        expected_status_codes=[200],
        ssl_check_enabled=False,
        check_type="http",
        keyword="healthy",
    )
    assert result.status == "down"
    assert "keyword" in (result.error_message or "").lower()


@pytest.mark.asyncio
@respx.mock
async def test_json_path_assertion_evaluated_on_http_check_type() -> None:
    """The bug this lot fixes: expected_json_path was gated on
    ``check_type == "json_path"`` — a migrated ``http`` monitor with the
    field still set would have had its assertion silently go inert."""
    respx.get("https://api.example.com/health").mock(
        return_value=httpx.Response(200, json={"status": "error"})
    )
    result = await perform_check(
        monitor_id="http-with-jsonpath",
        url="https://api.example.com/health",
        timeout_seconds=10,
        follow_redirects=True,
        expected_status_codes=[200],
        ssl_check_enabled=False,
        check_type="http",
        expected_json_path="$.status",
        expected_json_value="ok",
    )
    assert result.status == "down"
    assert "JSON path" in (result.error_message or "")


@pytest.mark.asyncio
@respx.mock
async def test_http_monitor_can_combine_keyword_and_json_path_assertions() -> None:
    """New capability the unification enables: both assertions on one
    monitor at once — impossible under the old two-type model."""
    respx.get("https://api.example.com/health").mock(
        return_value=httpx.Response(200, json={"status": "ok"})
    )
    result = await perform_check(
        monitor_id="http-with-both",
        url="https://api.example.com/health",
        timeout_seconds=10,
        follow_redirects=True,
        expected_status_codes=[200],
        ssl_check_enabled=False,
        check_type="http",
        keyword="status",
        expected_json_path="$.status",
        expected_json_value="ok",
    )
    assert result.status == "up"
