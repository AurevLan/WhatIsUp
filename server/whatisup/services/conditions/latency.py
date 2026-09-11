"""Latency anomaly — fixed threshold, rolling baseline, or statistical z-score.

Plan cap v2, F4 — one condition, three sensitivity modes, merged from what
used to be three separate ``AlertCondition`` members (``response_time_above``,
``response_time_above_baseline``, ``anomaly_detection``): they answered the
same question — "is this slow?" — and the old picker presented them flat, with
no way for an operator to tell which one to reach for.

The mode is inferred from **which one** of ``AlertRule.threshold_value`` /
``baseline_factor`` / ``anomaly_zscore_threshold`` is set — exactly like the
three old conditions used to be told apart by which enum member the rule
carried. ``schemas.alert.assert_latency_rule_is_fireable`` enforces that
exactly one of the three is set, both at creation and on the merged state
after a PATCH, so the priority order below (baseline, then z-score, then
absolute) only matters as a tie-break against malformed data that predates
that guard.

All three read the response time off the check that opened the incident, so
all three are unevaluable without one.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from whatisup.models.alert import AlertCondition
from whatisup.models.result import CheckResult
from whatisup.services.alert_conditions import (
    above_baseline_matches,
    anomaly_matches,
    response_time_above_matches,
)

from .base import (
    AlertConditionHandler,
    DispatchContext,
    DispatchDecision,
    PreviewContext,
    PreviewResult,
)

BASELINE_WINDOW = timedelta(days=7)


async def _rolling_average_ms(db, monitor_id, now: datetime) -> float | None:
    """Mean response time of the last 7 days of successful checks.

    Shared by dispatch and preview so the two cannot drift onto different
    windows — which is precisely how a preview ends up disagreeing with what
    pages at 3 a.m.
    """
    return (
        await db.execute(
            select(func.avg(CheckResult.response_time_ms)).where(
                CheckResult.monitor_id == monitor_id,
                CheckResult.checked_at >= now - BASELINE_WINDOW,
                CheckResult.response_time_ms.isnot(None),
            )
        )
    ).scalar_one_or_none()


class LatencyAnomalyHandler(AlertConditionHandler):
    condition = AlertCondition.latency_anomaly

    async def decide(self, dispatch: DispatchContext) -> DispatchDecision:
        rule, result = dispatch.rule, dispatch.result
        if result.response_time_ms is None:
            return DispatchDecision.no()

        if rule.baseline_factor is not None:
            baseline = await _rolling_average_ms(
                dispatch.db, dispatch.monitor.id, datetime.now(UTC)
            )
            fire = above_baseline_matches(result.response_time_ms, baseline, rule.baseline_factor)
            return DispatchDecision(fire=fire)

        if rule.anomaly_zscore_threshold is not None:
            # The z-score is computed once by ``process_check_result`` and
            # injected into ctx; recomputing it here would double the query
            # and could differ.
            if not anomaly_matches(dispatch.ctx.get("zscore"), rule.anomaly_zscore_threshold):
                return DispatchDecision.no()
            return DispatchDecision.yes(response_time_ms=result.response_time_ms)

        fire = response_time_above_matches(result.response_time_ms, rule.threshold_value)
        return DispatchDecision(fire=fire)

    async def preview(self, preview: PreviewContext) -> PreviewResult:
        rule = preview.rule

        if rule.baseline_factor is not None:
            return await self._preview_baseline(preview, rule.baseline_factor)
        if rule.anomaly_zscore_threshold is not None:
            return await self._preview_anomaly(preview, rule.anomaly_zscore_threshold)
        return self._preview_absolute(preview, rule.threshold_value)

    def _preview_absolute(self, preview: PreviewContext, threshold: float | None) -> PreviewResult:
        slow = []
        for mid in preview.monitor_ids:
            result = preview.latest.get(mid)
            if result is not None and response_time_above_matches(
                result.response_time_ms, threshold
            ):
                slow.append(f"{preview.monitors_by_id[mid].name} ({result.response_time_ms:.0f}ms)")

        if threshold is None:
            reason = "Seuil non défini — la règle ne peut pas se déclencher"
        elif slow:
            reason = f"Temps de réponse dépassé sur : {', '.join(slow)}"
        else:
            reason = f"Tous les monitors sont sous le seuil de {threshold}ms"
        return PreviewResult(would_fire=bool(slow), reason=reason, affected=slow)

    async def _preview_baseline(self, preview: PreviewContext, factor: float) -> PreviewResult:
        now = datetime.now(UTC)
        above = []
        for mid in preview.monitor_ids:
            result = preview.latest.get(mid)
            if result is None:
                continue
            baseline = await _rolling_average_ms(preview.db, mid, now)
            if above_baseline_matches(result.response_time_ms, baseline, factor):
                above.append(
                    f"{preview.monitors_by_id[mid].name} ({result.response_time_ms:.0f}ms"
                    f" > {factor}× {baseline:.0f}ms)"
                )

        reason = (
            f"Temps de réponse au-dessus de la baseline sur : {', '.join(above)}"
            if above
            else f"Tous les monitors sont sous {factor}× leur moyenne 7 jours"
        )
        return PreviewResult(would_fire=bool(above), reason=reason, affected=above)

    async def _preview_anomaly(
        self, preview: PreviewContext, zscore_threshold: float
    ) -> PreviewResult:
        # Same computation as process_check_result; returns None below 10 samples.
        from whatisup.services.anomaly import compute_zscore

        anomalous: list[str] = []
        insufficient = 0
        for mid in preview.monitor_ids:
            result = preview.latest.get(mid)
            if result is None or result.response_time_ms is None:
                continue
            zscore = await compute_zscore(preview.db, mid, result.response_time_ms)
            if zscore is None:
                insufficient += 1
                continue
            if anomaly_matches(zscore, zscore_threshold):
                anomalous.append(f"{preview.monitors_by_id[mid].name} (z-score {zscore:.1f})")

        if anomalous:
            reason = f"Anomalie de temps de réponse sur : {', '.join(anomalous)}"
        elif insufficient:
            reason = (
                f"Pas assez d'historique pour {insufficient} monitor(s)"
                " (minimum 10 mesures) — aucune anomalie détectable"
            )
        else:
            reason = "Aucune anomalie détectée sur les dernières mesures"
        return PreviewResult(would_fire=bool(anomalous), reason=reason, affected=anomalous)
