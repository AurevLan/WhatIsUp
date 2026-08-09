"""Pushed-metric conditions (plan V2, C-4) — thresholds on application metrics.

The odd family out: their verdict comes from ``custom_metrics``, not from a
``CheckResult``, and it is reached by ``services/metric_alerts.py`` rather than
by the check pipeline. By the time ``fire_alerts`` sees one, the evaluator has
already decided — it encoded its verdict by opening (or resolving) the very
incident being dispatched, and ``Incident.alert_rule_id`` ties the two together.
So ``decide`` has nothing left to weigh.

``preview`` does have work to do, and it deliberately answers a slightly
different question from the evaluator: "would this fire on the current value?",
ignoring ``min_duration_seconds``. That is what an operator is asking while
typing a threshold; the delay is stated in the reason rather than silently
turning a breaching metric into "would not fire".
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from whatisup.models.alert import AlertCondition
from whatisup.models.custom_metric import CustomMetric
from whatisup.services.alert_conditions import (
    DEFAULT_METRIC_WINDOW_SECONDS,
    metric_above_matches,
    metric_absent_matches,
    metric_below_matches,
)

from .base import (
    AlertConditionHandler,
    DispatchContext,
    DispatchDecision,
    PreviewContext,
    PreviewResult,
)

_OPEN_AND_RESOLVE = frozenset({"incident_opened", "incident_resolved"})


async def _latest_fresh_value(db, monitor_id, metric_name: str, window: int) -> float | None:
    now = datetime.now(UTC)
    return (
        await db.execute(
            select(CustomMetric.value)
            .where(
                CustomMetric.monitor_id == monitor_id,
                CustomMetric.metric_name == metric_name,
                CustomMetric.pushed_at >= now - timedelta(seconds=window),
                CustomMetric.pushed_at <= now,
            )
            .order_by(CustomMetric.pushed_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _ever_pushed(db, monitor_id, metric_name: str) -> bool:
    return (
        await db.execute(
            select(CustomMetric.id)
            .where(
                CustomMetric.monitor_id == monitor_id,
                CustomMetric.metric_name == metric_name,
                CustomMetric.pushed_at <= datetime.now(UTC),
            )
            .limit(1)
        )
    ).first() is not None


class _MetricHandler(AlertConditionHandler):
    """Shared shape: the evaluator already decided, the preview re-reads."""

    fires_on = _OPEN_AND_RESOLVE
    needs_check_result = False

    async def decide(self, dispatch: DispatchContext) -> DispatchDecision:
        return DispatchDecision.yes()

    def _unusable_reason(self, rule) -> str | None:
        """Why this rule can never match, if it can't."""
        if not rule.metric_name:
            return "Aucune métrique sélectionnée — la règle ne peut pas se déclencher"
        if self.condition is not AlertCondition.metric_absent and rule.threshold_value is None:
            return "Seuil non défini — la règle ne peut pas se déclencher"
        return None

    def _with_delay(self, reason: str, rule) -> str:
        if rule.min_duration_seconds:
            return f"{reason} (après {rule.min_duration_seconds}s de dépassement continu)"
        return reason

    async def preview(self, preview: PreviewContext) -> PreviewResult:
        rule = preview.rule
        unusable = self._unusable_reason(rule)
        if unusable:
            return PreviewResult(would_fire=False, reason=unusable)

        window = rule.metric_window_seconds or DEFAULT_METRIC_WINDOW_SECONDS
        matched: list[str] = []
        for mid in preview.monitor_ids:
            value = await _latest_fresh_value(preview.db, mid, rule.metric_name, window)
            label = await self._match_label(preview, mid, value, window)
            if label is not None:
                matched.append(label)

        if matched:
            return PreviewResult(
                would_fire=True,
                reason=self._with_delay(f"Déclencherait sur : {', '.join(matched)}", rule),
                affected=matched,
            )
        return PreviewResult(would_fire=False, reason=self._quiet_reason(rule, window))

    async def _match_label(self, preview, mid, value, window) -> str | None:
        raise NotImplementedError

    def _quiet_reason(self, rule, window: int) -> str:
        raise NotImplementedError


class MetricAboveHandler(_MetricHandler):
    condition = AlertCondition.metric_above

    async def _match_label(self, preview, mid, value, window) -> str | None:
        if not metric_above_matches(value, preview.rule.threshold_value):
            return None
        return f"{preview.monitors_by_id[mid].name} ({preview.rule.metric_name} = {value:g})"

    def _quiet_reason(self, rule, window: int) -> str:
        return (
            f"Aucune valeur récente de '{rule.metric_name}' au-dessus de "
            f"{rule.threshold_value} (fenêtre de fraîcheur : {window}s)"
        )


class MetricBelowHandler(_MetricHandler):
    condition = AlertCondition.metric_below

    async def _match_label(self, preview, mid, value, window) -> str | None:
        if not metric_below_matches(value, preview.rule.threshold_value):
            return None
        return f"{preview.monitors_by_id[mid].name} ({preview.rule.metric_name} = {value:g})"

    def _quiet_reason(self, rule, window: int) -> str:
        return (
            f"Aucune valeur récente de '{rule.metric_name}' en-dessous de "
            f"{rule.threshold_value} (fenêtre de fraîcheur : {window}s)"
        )


class MetricAbsentHandler(_MetricHandler):
    condition = AlertCondition.metric_absent

    async def _match_label(self, preview, mid, value, window) -> str | None:
        # The "ever pushed" guard is what keeps a typo in metric_name from
        # reading as a series that stopped reporting.
        ever = await _ever_pushed(preview.db, mid, preview.rule.metric_name)
        if not metric_absent_matches(value, ever):
            return None
        return f"{preview.monitors_by_id[mid].name} ({preview.rule.metric_name} muette)"

    def _quiet_reason(self, rule, window: int) -> str:
        return f"La métrique '{rule.metric_name}' a été poussée dans les {window} dernières s"
