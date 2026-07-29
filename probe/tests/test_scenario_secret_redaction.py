"""F10 — secret scenario variables must not reach the check result.

`_substitute_vars` interpolates variables into step params without looking at
the `secret` flag, so a failing assertion embedded a login password verbatim
into `error_message` / `scenario_result.error`. Those are POSTed to the central
API, stored, and readable through the results endpoints — defeating the
write-only masking the server applies to the very same values.
"""

from __future__ import annotations

from whatisup_probe.checkers.scenario import _redact_secrets, _substitute_vars

VARS = [
    {"name": "PASSWORD", "value": "S3cretPassw0rd", "secret": True},
    {"name": "USERNAME", "value": "alice@example.com", "secret": False},
]


def test_secret_value_is_blanked() -> None:
    text = "Step 3 (assert_text) failed: expected 'S3cretPassw0rd', got 'wrong'"
    scrubbed = _redact_secrets(text, VARS)
    assert "S3cretPassw0rd" not in scrubbed
    assert "***" in scrubbed
    assert "assert_text" in scrubbed  # the diagnostic part survives


def test_non_secret_values_are_kept() -> None:
    scrubbed = _redact_secrets("login as alice@example.com failed", VARS)
    assert "alice@example.com" in scrubbed


def test_substituted_param_is_redacted_again_on_the_way_out() -> None:
    """The end-to-end shape: substitute in, redact out."""
    param = _substitute_vars("{{USERNAME}}/{{PASSWORD}}", VARS)
    assert param == "alice@example.com/S3cretPassw0rd"
    assert _redact_secrets(f"failed on {param}", VARS) == "failed on alice@example.com/***"


def test_multiple_occurrences_all_blanked() -> None:
    text = "S3cretPassw0rd ... S3cretPassw0rd"
    assert "S3cretPassw0rd" not in _redact_secrets(text, VARS)


def test_short_secrets_are_left_alone() -> None:
    """Blanking a 2-char value would mangle unrelated text for no real gain."""
    short = [{"name": "PIN", "value": "42", "secret": True}]
    assert _redact_secrets("timeout after 42s", short) == "timeout after 42s"


def test_redaction_handles_empty_and_none() -> None:
    assert _redact_secrets(None, VARS) is None
    assert _redact_secrets("", VARS) == ""


def test_secret_extracted_at_runtime_is_still_redacted() -> None:
    """An extract step can overwrite an existing secret variable's value."""
    variables = [{"name": "TOKEN", "value": "initial-value", "secret": True}]
    variables[0]["value"] = "runtime-captured-token"
    scrubbed = _redact_secrets("got runtime-captured-token", variables)
    assert "runtime-captured-token" not in scrubbed
