"""Contract for an alert condition.

Why this layer exists
─────────────────────
``AlertCondition`` used to be dispatched by three parallel ``if/elif`` chains:
``fire_alerts`` (what actually pages), ``simulate_rule`` (the UI preview) and
``compute_preview`` (the "≈ N / 30 j" impact badge). Adding a condition meant
editing three files, and **every divergence between them is silent** — the
preview cheerfully answers "would not fire" for a rule that pages every night,
and nothing fails. That is not hypothetical: v1.16.2 (R-1) shipped a fix for
exactly that drift, where the preview knew four of the conditions the dispatch
handled and disagreed with it on two more.

R-1 factored out the *predicates* (``services/alert_conditions.py``) so both
sides at least compute the same booleans. It did not factor out the *structure*,
so the two call sites could still drift on which event types fire, which fields
are required, and what "no data" means.

This module closes that: one class per condition, holding **both** the dispatch
decision and the preview, next to each other. They can still be written to
disagree — but now you have to look straight at the other one to do it.

The registry is the third of its kind in this codebase, and deliberately mirrors
the two that already exist (``services/channels`` for alert channels,
``probe/whatisup_probe/checkers`` for check types).
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from whatisup.models.alert import AlertCondition, AlertRule
    from whatisup.models.incident import Incident
    from whatisup.models.monitor import Monitor
    from whatisup.models.result import CheckResult


@dataclass(frozen=True)
class DispatchContext:
    """Everything a condition may consult to decide whether to page, now."""

    db: AsyncSession
    incident: Incident
    monitor: Monitor
    rule: AlertRule
    event_type: str
    #: ``None`` whenever the caller has no check in hand — the heartbeat
    #: checker, the renotify loop and the pushed-metric evaluator all open or
    #: resolve incidents without one. Handlers that set ``needs_check_result``
    #: are never called in that case, so they may treat this as non-None.
    result: CheckResult | None
    #: Message context built by ``fire_alerts``; carries pre-computed values
    #: such as ``zscore`` and the pushed-metric payload.
    ctx: dict[str, Any]


@dataclass(frozen=True)
class DispatchDecision:
    """Whether to page, plus anything the channels should be told."""

    fire: bool
    #: Merged into the channel message context when firing.
    ctx_extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def no(cls) -> DispatchDecision:
        return cls(fire=False)

    @classmethod
    def yes(cls, **ctx_extra: Any) -> DispatchDecision:
        return cls(fire=True, ctx_extra=ctx_extra)


@dataclass(frozen=True)
class PreviewContext:
    """Current state of the rule's monitors, for the "would this fire?" answer."""

    db: AsyncSession
    rule: AlertRule
    monitors: list[Monitor]
    monitors_by_id: dict[uuid.UUID, Monitor]
    #: Latest check per monitor. Empty for conditions that declare
    #: ``needs_check_result = False`` — the query is skipped for them, since on
    #: a partitioned ``check_results`` it is far from free.
    latest: dict[uuid.UUID, CheckResult]

    @property
    def monitor_ids(self) -> list[uuid.UUID]:
        return [m.id for m in self.monitors]


@dataclass(frozen=True)
class PreviewResult:
    """Answer to "would this rule fire right now?", in the operator's words."""

    would_fire: bool
    #: Shown verbatim in the UI. Say *why* — a bare "no" is what sends people
    #: hunting for a rule that was simply missing a threshold.
    reason: str
    #: Human-readable per-monitor detail ("api-prod (842ms)").
    affected: list[str] = field(default_factory=list)


class AlertConditionHandler(ABC):
    """One alert condition: how it pages, and how it previews.

    Subclasses declare ``condition`` and implement both methods. Registration
    happens in ``services/conditions/__init__.py``.
    """

    #: The enum member this handler serves.
    condition: AlertCondition

    #: Event types this condition ever dispatches on. ``fire_alerts`` checks
    #: this before calling ``decide``, so a handler never has to re-test it.
    fires_on: frozenset[str] = frozenset({"incident_opened"})

    #: True when the **dispatch** verdict is read off a ``CheckResult``.
    #: ``fire_alerts`` skips the handler when it has none — before this existed,
    #: an ``ssl_expiry`` rule on a heartbeat monitor raised AttributeError from
    #: inside a background loop.
    needs_check_result: bool = True

    #: True when the **preview** reads the monitors' latest checks. Separate
    #: from the above on purpose, and they genuinely differ: ``any_down``
    #: dispatches off the incident alone (no check needed) but previews by
    #: looking at each monitor's current status (checks very much needed).
    #: Conflating the two silently made the preview answer "would not fire" for
    #: a monitor that was down — caught by ``test_simulate_rule_any_down_fires``.
    #: Defaults to ``needs_check_result`` via ``__init_subclass__``.
    preview_reads_checks: bool = True

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        # A subclass that only sets ``needs_check_result`` keeps the two aligned,
        # which is the right default for every condition but availability.
        if "preview_reads_checks" not in cls.__dict__ and "needs_check_result" in cls.__dict__:
            cls.preview_reads_checks = cls.needs_check_result

    @abstractmethod
    async def decide(self, dispatch: DispatchContext) -> DispatchDecision:
        """Should this rule page for this incident, right now?"""
        ...

    @abstractmethod
    async def preview(self, preview: PreviewContext) -> PreviewResult:
        """Would this rule fire against the monitors' current state?

        Must agree with ``decide`` on the same data. Where it deliberately does
        not — the pushed-metric conditions ignore ``min_duration_seconds``,
        because the operator is asking about the current value while typing a
        threshold — say so in the ``reason``.
        """
        ...
