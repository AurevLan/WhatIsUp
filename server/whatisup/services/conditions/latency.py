"""Latency conditions — fixed threshold, rolling baseline, statistical anomaly.

Three answers to "is this slow?", in increasing order of how much history they
need: a number you chose, a multiple of the last 7 days, and a z-score against
the same time-of-day window. All three read the response time off the check that
opened the incident, so all three are unevaluable without one.
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


class ResponseTimeAboveHandler(AlertConditionHandler):
    condition = AlertCondition.response_time_above

    async def decide(self, dispatch: DispatchContext) -> DispatchDecision:
        fire = response_time_above_matches(
            dispatch.result.response_time_ms, dispatch.rule.threshold_value
        )
        return DispatchDecision(fire=fire)

    async def preview(self, preview: PreviewContext) -> PreviewResult:
        threshold = preview.rule.threshold_value
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


class ResponseTimeAboveBaselineHandler(AlertConditionHandler):
    condition = AlertCondition.response_time_above_baseline

    async def decide(self, dispatch: DispatchContext) -> DispatchDecision:
        rule, result = dispatch.rule, dispatch.result
        if rule.baseline_factor is None or result.response_time_ms is None:
            return DispatchDecision.no()
        baseline = await _rolling_average_ms(dispatch.db, dispatch.monitor.id, datetime.now(UTC))
        fire = above_baseline_matches(result.response_time_ms, baseline, rule.baseline_factor)
        return DispatchDecision(fire=fire)

    async def preview(self, preview: PreviewContext) -> PreviewResult:
        factor = preview.rule.baseline_factor
        if factor is None:
            return PreviewResult(
                would_fire=False,
                reason="Facteur de baseline non défini — la règle ne peut pas se déclencher",
            )

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


class AnomalyDetectionHandler(AlertConditionHandler):
    condition = AlertCondition.anomaly_detection

    async def decide(self, dispatch: DispatchContext) -> DispatchDecision:
        result = dispatch.result
        if result.response_time_ms is None:
            return DispatchDecision.no()
        # The z-score is computed once by ``process_check_result`` and injected
        # into ctx; recomputing it here would double the query and could differ.
        if not anomaly_matches(dispatch.ctx.get("zscore"), dispatch.rule.anomaly_zscore_threshold):
            return DispatchDecision.no()
        return DispatchDecision.yes(response_time_ms=result.response_time_ms)

    async def preview(self, preview: PreviewContext) -> PreviewResult:
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
            if anomaly_matches(zscore, preview.rule.anomaly_zscore_threshold):
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
