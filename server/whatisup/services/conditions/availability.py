"""Availability — the monitor is down, by some quorum of its probes.

The only condition that decides from the *incident* rather than from a value:
there is nothing to compare, the incident's existence and its scope are the
whole verdict. That is also why it is the only one that dispatches on
``incident_resolved`` as well as on open — a recovery notification only makes
sense for something that was down.

Plan cap v2, F1-conditions — this handler merges what used to be two: the old
``any_down`` ("at least one probe reports down") and ``all_down`` ("every
probe reports down at once", a.k.a. global outage) were degenerate cases of
the same question — what fraction of probes down should page. See
``AlertRule.quorum_ratio``'s docstring for the exact boundary this handler
honours, and for why intermediate quorums aren't evaluated precisely yet.
"""

from __future__ import annotations

from whatisup.models.alert import AlertCondition
from whatisup.models.incident import IncidentScope
from whatisup.models.result import CheckStatus

from .base import (
    AlertConditionHandler,
    DispatchContext,
    DispatchDecision,
    PreviewContext,
    PreviewResult,
)

_OPEN_AND_RESOLVE = frozenset({"incident_opened", "incident_resolved"})

#: quorum_ratio at or above this behaves like the old ``all_down``; anything
#: below (including unset/None) behaves like the old ``any_down``.
_REQUIRE_ALL_THRESHOLD = 1.0


def _down_monitor_names(preview: PreviewContext) -> list[str]:
    names = []
    for mid in preview.monitor_ids:
        result = preview.latest.get(mid)
        if result is None:
            continue  # never checked — absence of data is not a failure
        if result.status != CheckStatus.up:
            names.append(preview.monitors_by_id[mid].name)
    return names


class AvailabilityHandler(AlertConditionHandler):
    condition = AlertCondition.availability
    fires_on = _OPEN_AND_RESOLVE
    needs_check_result = False  # the incident is the signal, not a check row
    preview_reads_checks = True  # ...but the preview asks each monitor's status

    async def decide(self, dispatch: DispatchContext) -> DispatchDecision:
        quorum = dispatch.rule.quorum_ratio or 0.0
        if quorum < _REQUIRE_ALL_THRESHOLD:
            return DispatchDecision.yes()
        # "every probe down at once" (old all_down): a partial outage must not
        # page. Only gated on open: once it has paged, the matching recovery
        # has to go out even if the incident narrowed to a single probe
        # before resolving.
        if (
            dispatch.event_type == "incident_opened"
            and dispatch.incident.scope != IncidentScope.global_
        ):
            return DispatchDecision.no()
        return DispatchDecision.yes()

    async def preview(self, preview: PreviewContext) -> PreviewResult:
        down = _down_monitor_names(preview)
        quorum = preview.rule.quorum_ratio or 0.0

        if quorum < _REQUIRE_ALL_THRESHOLD:
            if down:
                reason = f"{len(down)} monitor(s) actuellement en panne : {', '.join(down)}"
            else:
                reason = "Tous les monitors sont UP"
            return PreviewResult(would_fire=bool(down), reason=reason, affected=down)

        total = len(preview.monitor_ids)
        would_fire = len(down) == total
        reason = (
            "Panne globale — tous les monitors sont down"
            if would_fire
            else f"{len(down)}/{total} monitors en panne (pas encore tous)"
        )
        return PreviewResult(would_fire=would_fire, reason=reason, affected=down)
