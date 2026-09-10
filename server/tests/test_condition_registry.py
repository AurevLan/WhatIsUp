"""Structural guarantees of the alert-condition registry.

The registry exists because three parallel ``if/elif`` chains over
``AlertCondition`` had already drifted once (R-1, v1.16.2) and every drift is
silent — a preview that answers "would not fire" for a rule that pages nightly
fails nothing. These tests make the drift loud instead.
"""

from __future__ import annotations

import inspect

import pytest

from whatisup.models.alert import AlertCondition
from whatisup.services.conditions import CONDITION_REGISTRY, get_handler

_EVENT_TYPES = {"incident_opened", "incident_resolved"}


def test_every_condition_has_a_handler():
    """A new enum member without a handler must not reach production.

    Without this, adding a condition yields a rule the UI happily creates, the
    API happily stores, and nothing ever evaluates.
    """
    missing = [c for c in AlertCondition if c not in CONDITION_REGISTRY]
    assert missing == []


def test_no_handler_without_a_condition():
    """And no orphan handler left behind by a removed enum member.

    ``tls_grade_below`` was exactly that: an enum value the PG type never had,
    which 500'd on INSERT rather than 422'ing at the door.
    """
    orphans = [c for c in CONDITION_REGISTRY if c not in set(AlertCondition)]
    assert orphans == []


@pytest.mark.parametrize("condition", list(AlertCondition))
def test_handler_contract_is_honoured(condition: AlertCondition):
    handler = CONDITION_REGISTRY[condition]

    assert handler.condition is condition, "handler registered under the wrong key"
    assert handler.fires_on, "a condition that fires on no event type can never alert"
    assert handler.fires_on <= _EVENT_TYPES, f"unknown event type in {handler.fires_on}"

    for name in ("decide", "preview"):
        method = getattr(type(handler), name)
        assert inspect.iscoroutinefunction(method), f"{name} must be async"


@pytest.mark.parametrize("condition", list(AlertCondition))
def test_a_condition_that_cannot_dispatch_cannot_preview_blindly(condition: AlertCondition):
    """``preview_reads_checks`` must be a deliberate choice, never an accident.

    ``availability`` is the case that makes this worth pinning: it dispatches
    off the incident alone but previews off each monitor's latest check.
    Deriving one flag from the other made the preview claim a down monitor
    was fine.
    """
    handler = CONDITION_REGISTRY[condition]
    if handler.needs_check_result:
        assert handler.preview_reads_checks, (
            "a condition whose dispatch reads a check must read one to preview too"
        )


def test_availability_is_the_only_condition_with_dispatch_and_preview_diverging():
    """Plan cap v2, 6f — the C-4 pushed-metric conditions used to be the other
    three whose ``preview_reads_checks`` diverged from ``needs_check_result``;
    cutting them (C1) leaves ``availability`` as the sole deliberate
    divergence: it dispatches off the incident alone (``needs_check_result``
    False) but previews off each monitor's current status
    (``preview_reads_checks`` True). Confusing the two made the preview
    answer "would not fire" for a monitor that was down
    (``test_simulate_rule_any_down_fires``, pre-6f).
    """
    diverging = {
        c for c, h in CONDITION_REGISTRY.items() if h.needs_check_result != h.preview_reads_checks
    }
    assert diverging == {AlertCondition.availability}


def test_get_handler_accepts_the_raw_string():
    """Rules reach this both as ORM enums and as matrix payload strings."""
    assert get_handler("availability") is CONDITION_REGISTRY[AlertCondition.availability]
    assert (
        get_handler(AlertCondition.availability) is CONDITION_REGISTRY[AlertCondition.availability]
    )
    assert get_handler("not_a_condition") is None
    # Retired members (plan cap v2, 6f) must not resolve to a handler by
    # accident — they are plain strings now (AlertCondition.condition is a
    # VARCHAR, not a native enum), so a stale row or payload must 404/skip
    # rather than silently dispatching under the wrong logic.
    assert get_handler("any_down") is None
    assert get_handler("all_down") is None
    assert get_handler("response_time_above") is None
    assert get_handler("metric_above") is None
