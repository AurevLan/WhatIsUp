"""Availability conditions — the monitor is down, somewhere or everywhere.

The only two conditions that decide from the *incident* rather than from a
value: there is nothing to compare, the incident's existence and its scope are
the whole verdict. That is also why they are the only two that dispatch on
``incident_resolved`` as well as on open — a recovery notification only makes
sense for something that was down.
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


def _down_monitor_names(preview: PreviewContext) -> list[str]:
    names = []
    for mid in preview.monitor_ids:
        result = preview.latest.get(mid)
        if result is None:
            continue  # never checked — absence of data is not a failure
        if result.status != CheckStatus.up:
            names.append(preview.monitors_by_id[mid].name)
    return names


class AnyDownHandler(AlertConditionHandler):
    condition = AlertCondition.any_down
    fires_on = _OPEN_AND_RESOLVE
    needs_check_result = False  # the incident is the signal, not a check row
    preview_reads_checks = True  # ...but the preview asks each monitor's status

    async def decide(self, dispatch: DispatchContext) -> DispatchDecision:
        return DispatchDecision.yes()

    async def preview(self, preview: PreviewContext) -> PreviewResult:
        down = _down_monitor_names(preview)
        if down:
            reason = f"{len(down)} monitor(s) actuellement en panne : {', '.join(down)}"
        else:
            reason = "Tous les monitors sont UP"
        return PreviewResult(would_fire=bool(down), reason=reason, affected=down)


class AllDownHandler(AlertConditionHandler):
    condition = AlertCondition.all_down
    fires_on = _OPEN_AND_RESOLVE
    needs_check_result = False
    preview_reads_checks = True

    async def decide(self, dispatch: DispatchContext) -> DispatchDecision:
        # A partial outage must not page an "all down" rule. Only gated on open:
        # once it has paged, the matching recovery has to go out even if the
        # incident narrowed to a single probe before resolving.
        if (
            dispatch.event_type == "incident_opened"
            and dispatch.incident.scope != IncidentScope.global_
        ):
            return DispatchDecision.no()
        return DispatchDecision.yes()

    async def preview(self, preview: PreviewContext) -> PreviewResult:
        down = _down_monitor_names(preview)
        total = len(preview.monitor_ids)
        would_fire = len(down) == total
        reason = (
            "Panne globale — tous les monitors sont down"
            if would_fire
            else f"{len(down)}/{total} monitors en panne (pas encore tous)"
        )
        return PreviewResult(would_fire=would_fire, reason=reason, affected=down)
